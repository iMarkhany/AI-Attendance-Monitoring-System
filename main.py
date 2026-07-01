"""FastAPI entry point for the AI Student Engagement System.

Endpoints:

POST   /lecture/start              Start a new lecture
POST   /lecture/{id}/end           End a lecture
GET    /lecture/list               List all lectures
GET    /lecture/{id}/summary       Summary statistics for one lecture

POST   /analyze                    Analyze a single frame
POST   /analyze_batch              Analyze multiple frames in one call
GET    /report/{student_id}        Per-student report (overall or per-lecture)
GET    /reports/all                Reports for every active student
GET    /health                     Liveness probe
GET    /                           Redirect to /docs
"""

from __future__ import annotations

import logging
from collections import defaultdict
from time import time
from typing import List, Optional

import numpy as np
from deepface import DeepFace
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.analytics import lecture_manager
from app.analytics.session_tracker import _active_sessions, get_session
from app.config import DEFAULT_LECTURE_ID
from app.models import (
    AnalyzeBatchRequest,
    AnalyzeRequest,
    AnalyzeResponse,
    LectureInfo,
    LectureSummary,
    ReportResponse,
    StartLectureRequest,
)
from app.services.emotion_service import EmotionService
from app.utils.image_utils import decode_base64_image

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Student Engagement System",
    description=(
        "Detects student emotions from webcam frames using DeepFace, "
        "logs them to a CSV consumable by the R Shiny dashboard, and "
        "exposes live reports for httr-based real-time integration."
    ),
    version="2.0.0",
)

# CORS so the R Shiny dashboard (or any browser-based client) can call us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    """Pre-warm DeepFace so the first real request isn't slow."""
    logger.info("Pre-warming DeepFace model with a dummy frame...")
    try:
        dummy = np.zeros((224, 224, 3), dtype=np.uint8)
        DeepFace.analyze(dummy, actions=["emotion"], enforce_detection=False)
    except Exception:  # noqa: BLE001
        pass
    logger.info("DeepFace ready.")


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Crude per-IP rate limiter: 10 req/sec rolling window."""

    def __init__(self, app):
        super().__init__(app)
        self.records: dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next):
        client = request.client.host if request.client else "unknown"
        now = time()
        history = [t for t in self.records.get(client, []) if now - t < 1.0]
        if len(history) >= 10:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded."},
            )
        history.append(now)
        self.records[client] = history
        return await call_next(request)


app.add_middleware(RateLimitMiddleware)


# ---------------------------------------------------------------------------
# Root / health
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health_check():
    return {"status": "System Online", "model": "DeepFace Emotion Preloaded"}


# ---------------------------------------------------------------------------
# Lecture lifecycle
# ---------------------------------------------------------------------------
@app.post("/lecture/start", response_model=LectureInfo)
async def start_lecture(payload: StartLectureRequest):
    info = lecture_manager.start_lecture(
        lecture_id=payload.lecture_id,
        title=payload.title,
        lecturer_id=payload.lecturer_id,
    )
    logger.info("Started lecture %s", info["lecture_id"])
    return LectureInfo(
        lecture_id=info["lecture_id"],
        title=info["title"] or None,
        lecturer_id=info["lecturer_id"] or None,
        started_at=info["started_at"],
        ended_at=info["ended_at"] or None,
        active=info["active"] == "True",
    )


@app.post("/lecture/{lecture_id}/end", response_model=LectureInfo)
async def end_lecture(lecture_id: str):
    info = lecture_manager.end_lecture(lecture_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Lecture not found.")
    logger.info("Ended lecture %s", lecture_id)
    return LectureInfo(
        lecture_id=info["lecture_id"],
        title=info["title"] or None,
        lecturer_id=info["lecturer_id"] or None,
        started_at=info["started_at"],
        ended_at=info["ended_at"] or None,
        active=info["active"] == "True",
    )


@app.get("/lecture/list", response_model=List[LectureInfo])
async def list_lectures():
    return [
        LectureInfo(
            lecture_id=row["lecture_id"],
            title=row["title"] or None,
            lecturer_id=row["lecturer_id"] or None,
            started_at=row["started_at"],
            ended_at=row["ended_at"] or None,
            active=row["active"] == "True",
        )
        for row in lecture_manager.list_lectures()
    ]


@app.get("/lecture/{lecture_id}/summary", response_model=LectureSummary)
async def lecture_summary(lecture_id: str):
    """Aggregate engagement stats for a specific lecture across all students."""
    total_frames = 0
    unique_students: set[str] = set()
    engagement_sum = 0.0
    emotion_dist: dict[str, int] = defaultdict(int)

    for student_id, session in _active_sessions.items():
        per_lec = session.per_lecture.get(lecture_id)
        if not per_lec or per_lec["total_frames"] == 0:
            continue
        unique_students.add(student_id)
        total_frames += per_lec["total_frames"]
        engagement_sum += per_lec["engagement_sum"]
        for emo, count in per_lec["emotion_distribution"].items():
            emotion_dist[emo] += count

    if total_frames == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No data recorded for lecture {lecture_id}.",
        )

    avg_engagement = engagement_sum / total_frames
    return LectureSummary(
        lecture_id=lecture_id,
        total_frames=total_frames,
        unique_students=len(unique_students),
        average_engagement=round(avg_engagement, 3),
        emotion_distribution=dict(emotion_dist),
    )


# ---------------------------------------------------------------------------
# Frame analysis
# ---------------------------------------------------------------------------
@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_endpoint(payload: AnalyzeRequest):
    try:
        frame = decode_base64_image(payload.image_base64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    ai_result = EmotionService.analyze_face(frame)
    session = get_session(payload.student_id)
    result = session.process_frame(
        ai_result["emotion"],
        ai_result["confidence"],
        payload.lecture_id,
    )
    return result


@app.post("/analyze_batch", response_model=List[AnalyzeResponse])
async def analyze_batch_endpoint(payload: AnalyzeBatchRequest):
    out = []
    for req in payload.requests:
        try:
            frame = decode_base64_image(req.image_base64)
            ai_result = EmotionService.analyze_face(frame)
            session = get_session(req.student_id)
            out.append(
                session.process_frame(
                    ai_result["emotion"],
                    ai_result["confidence"],
                    req.lecture_id,
                )
            )
        except ValueError:
            out.append(
                AnalyzeResponse(
                    student_id=req.student_id,
                    lecture_id=req.lecture_id,
                    timestamp="",
                    emotion="Error",
                    confidence=0.0,
                    engagement_score=0.0,
                    status="Error",
                    alert="Invalid Base64",
                )
            )
    return out


# ---------------------------------------------------------------------------
# Reports — these are what R hits via httr
# ---------------------------------------------------------------------------
@app.get("/report/{student_id}", response_model=ReportResponse)
async def get_report(student_id: str, lecture_id: Optional[str] = None):
    """Per-student rolling report.

    If ``lecture_id`` is supplied as a query param, the response is scoped
    to that lecture only — otherwise it covers the entire student session.
    """
    session = _active_sessions.get(student_id)
    if session is None or session.total_frames == 0:
        raise HTTPException(status_code=404, detail="No data for this student.")

    if lecture_id is not None:
        per_lec = session.per_lecture.get(lecture_id)
        if not per_lec or per_lec["total_frames"] == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No data for {student_id} in lecture {lecture_id}.",
            )
        attendance = (per_lec["present_frames"] / per_lec["total_frames"]) * 100
        avg_eng = per_lec["engagement_sum"] / per_lec["total_frames"]
        return ReportResponse(
            student_id=student_id,
            lecture_id=lecture_id,
            total_frames=per_lec["total_frames"],
            attendance_rate=round(attendance, 2),
            average_engagement=round(avg_eng, 3),
            current_trend=session.get_trend(),
            emotion_distribution=dict(per_lec["emotion_distribution"]),
            alerts_summary=list(set(session.alerts)),
        )

    attendance = (session.present_frames / session.total_frames) * 100
    avg_eng = sum(session.history) / len(session.history)
    return ReportResponse(
        student_id=student_id,
        lecture_id=None,
        total_frames=session.total_frames,
        attendance_rate=round(attendance, 2),
        average_engagement=round(avg_eng, 3),
        current_trend=session.get_trend(),
        emotion_distribution=dict(session.emotion_distribution),
        alerts_summary=list(set(session.alerts)),
    )


@app.get("/reports/all", response_model=List[ReportResponse])
async def get_all_reports():
    """Snapshot of every active student. Used by the Shiny dashboard's
    real-time tab."""
    out = []
    for student_id, session in _active_sessions.items():
        if session.total_frames == 0:
            continue
        attendance = (session.present_frames / session.total_frames) * 100
        avg_eng = sum(session.history) / len(session.history)
        out.append(
            ReportResponse(
                student_id=student_id,
                lecture_id=None,
                total_frames=session.total_frames,
                attendance_rate=round(attendance, 2),
                average_engagement=round(avg_eng, 3),
                current_trend=session.get_trend(),
                emotion_distribution=dict(session.emotion_distribution),
                alerts_summary=list(set(session.alerts)),
            )
        )
    return out

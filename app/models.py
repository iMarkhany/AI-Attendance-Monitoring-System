"""Pydantic request/response models.

The shape of these directly defines the FastAPI auto-generated /docs
endpoint, so changes here ripple into the OpenAPI schema R uses via httr.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.config import DEFAULT_LECTURE_ID


# ---------------------------------------------------------------------------
# Frame analysis
# ---------------------------------------------------------------------------
class AnalyzeRequest(BaseModel):
    student_id: str
    image_base64: str
    lecture_id: str = Field(
        default=DEFAULT_LECTURE_ID,
        description="Identifier of the lecture this frame belongs to.",
    )


class AnalyzeBatchRequest(BaseModel):
    requests: List[AnalyzeRequest]


class AnalyzeResponse(BaseModel):
    student_id: str
    lecture_id: str
    timestamp: str
    emotion: str
    confidence: float
    engagement_score: float
    status: str
    alert: Optional[str] = None


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
class ReportResponse(BaseModel):
    student_id: str
    lecture_id: Optional[str] = None
    total_frames: int
    attendance_rate: float
    average_engagement: float
    current_trend: str
    emotion_distribution: Dict[str, int]
    alerts_summary: List[str]


# ---------------------------------------------------------------------------
# Lecture management
# ---------------------------------------------------------------------------
class StartLectureRequest(BaseModel):
    lecture_id: Optional[str] = Field(
        default=None,
        description="Optional caller-supplied ID. Auto-generated if omitted.",
    )
    title: Optional[str] = None
    lecturer_id: Optional[str] = None


class LectureInfo(BaseModel):
    lecture_id: str
    title: Optional[str] = None
    lecturer_id: Optional[str] = None
    started_at: str
    ended_at: Optional[str] = None
    active: bool


class LectureSummary(BaseModel):
    lecture_id: str
    total_frames: int
    unique_students: int
    average_engagement: float
    emotion_distribution: Dict[str, int]

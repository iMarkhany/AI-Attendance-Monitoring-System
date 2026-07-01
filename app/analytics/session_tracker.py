"""Per-student rolling session state.

Holds the in-memory rolling statistics for each student (EMA engagement,
emotion distribution, alert history) and persists each processed frame
to the shared CSV log so R can pick it up.
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict

from app.analytics.csv_logger import log_frame
from app.config import (
    ABSENCE_FRAME_THRESHOLD,
    EMA_ALPHA,
    EMOTION_WEIGHTS,
    LOW_ENGAGEMENT_THRESHOLD,
    TREND_WINDOW_SIZE,
)

logger = logging.getLogger(__name__)


class StudentSession:
    """Rolling state for one student.

    A session is logically scoped to "the lifetime of this Python process"
    — it accumulates everything that student does across all lectures.
    Per-lecture aggregation is recovered downstream by R from the CSV log.
    """

    def __init__(self, student_id: str):
        self.student_id = student_id
        self.total_frames = 0
        self.present_frames = 0
        self.absent_streak = 0
        self.status = "Present"

        self.history: list[float] = []
        self.ema_score = 0.0
        self.emotion_distribution: Dict[str, int] = defaultdict(int)
        self.alerts: list[str] = []

        # Per-lecture rolling counters for the live /report endpoint
        self.per_lecture: Dict[str, Dict] = defaultdict(
            lambda: {
                "total_frames": 0,
                "present_frames": 0,
                "engagement_sum": 0.0,
                "emotion_distribution": defaultdict(int),
            }
        )

    def process_frame(
        self,
        emotion: str,
        confidence: float,
        lecture_id: str,
    ) -> dict:
        """Update rolling state with a new emotion observation and persist it."""
        self.total_frames += 1
        alert = None
        per_lec = self.per_lecture[lecture_id]
        per_lec["total_frames"] += 1

        if emotion in ("Absent", "Error"):
            self.absent_streak += 1
            raw_score = 0.0
            if self.absent_streak >= ABSENCE_FRAME_THRESHOLD:
                self.status = "Absent"
                alert = (
                    f"Student absent for {self.absent_streak} consecutive frames."
                )
        else:
            self.present_frames += 1
            self.absent_streak = 0
            self.status = "Present"
            self.emotion_distribution[emotion] += 1
            per_lec["present_frames"] += 1
            per_lec["emotion_distribution"][emotion] += 1
            raw_score = EMOTION_WEIGHTS.get(emotion.lower(), 0.5)

        # Exponential moving average for stable engagement scoring
        if self.total_frames == 1:
            self.ema_score = raw_score
        else:
            self.ema_score = (
                EMA_ALPHA * raw_score + (1 - EMA_ALPHA) * self.ema_score
            )

        self.history.append(self.ema_score)
        per_lec["engagement_sum"] += self.ema_score

        # Engagement alert
        if self.status == "Present" and self.ema_score < LOW_ENGAGEMENT_THRESHOLD:
            alert = "Low engagement detected."

        if alert:
            self.alerts.append(alert)
            logger.warning("[%s] ALERT: %s", self.student_id, alert)

        # Persist to CSV — this is what R consumes
        timestamp = log_frame(
            student_id=self.student_id,
            emotion=emotion,
            confidence=confidence,
            lecture_id=lecture_id,
            engagement_score=round(self.ema_score, 4),
        )

        return {
            "student_id": self.student_id,
            "lecture_id": lecture_id,
            "timestamp": timestamp,
            "emotion": emotion,
            "confidence": confidence,
            "engagement_score": round(self.ema_score, 3),
            "status": self.status,
            "alert": alert,
        }

    def get_trend(self) -> str:
        """Classify the recent engagement trajectory."""
        if len(self.history) < TREND_WINDOW_SIZE:
            return "stable"
        recent = self.history[-TREND_WINDOW_SIZE:]
        if all(x > y for x, y in zip(recent, recent[1:])):
            return "decreasing"
        if all(x < y for x, y in zip(recent, recent[1:])):
            return "increasing"
        return "stable"


# Global registry of active sessions (in-memory; CSV is the durable store)
_active_sessions: Dict[str, StudentSession] = {}


def get_session(student_id: str) -> StudentSession:
    if student_id not in _active_sessions:
        _active_sessions[student_id] = StudentSession(student_id)
    return _active_sessions[student_id]


def reset_sessions() -> None:
    _active_sessions.clear()

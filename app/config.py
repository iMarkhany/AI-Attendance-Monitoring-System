"""Central configuration for the engagement system.

Two kinds of settings live here:
1. Domain knobs the analytics layer reads (emotion weights, thresholds).
2. Filesystem paths shared by the FastAPI backend and the R Shiny dashboard.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------
# Resolve project root relative to this file so the code works regardless of
# where uvicorn is launched from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# This is the single source of truth that R reads. The schema MUST match
# the columns expected by r_dashboard/app.R.
EMOTIONS_LOG_CSV = DATA_DIR / "emotions_log.csv"
LECTURES_CSV = DATA_DIR / "lectures.csv"

# Required schema, in column order. Matches the project brief's expected
# dataset structure (Student_ID, Time, Emotion, Confidence, Lecture_ID) plus
# a derived engagement_score column for convenience in R.
CSV_COLUMNS = [
    "student_id",
    "timestamp",      # ISO 8601 (e.g. 2025-04-12T10:05:33)
    "emotion",
    "confidence",
    "lecture_id",
    "engagement_score",
]

# ---------------------------------------------------------------------------
# Engagement scoring
# ---------------------------------------------------------------------------
# DeepFace returns one of these seven emotions. We map each to a weight in
# [0, 1] representing how engaged that emotional state suggests the student is.
# The brief mentions "happy, neutral, bored, confused" — DeepFace doesn't have
# explicit "bored" or "confused" labels, so we treat sad/neutral as proxies
# for boredom and fear/surprise as proxies for confusion.
EMOTION_WEIGHTS = {
    "happy": 1.0,
    "surprise": 0.8,
    "neutral": 0.6,
    "sad": 0.3,
    "fear": 0.2,
    "angry": 0.2,
    "disgust": 0.1,
}

# Thresholds and smoothing
LOW_ENGAGEMENT_THRESHOLD = 0.4   # EMA below this triggers an alert
ABSENCE_FRAME_THRESHOLD = 10     # Consecutive missing-face frames before flagging absent
TREND_WINDOW_SIZE = 5            # Frames used to detect a "decreasing" trend
EMA_ALPHA = 0.3                  # Exponential moving average smoothing factor

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_LECTURE_ID = "L_default"  # Used when /analyze is called without lecture_id

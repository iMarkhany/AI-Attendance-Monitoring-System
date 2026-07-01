"""Quick smoke test for the analytics layer.

Bypasses DeepFace (which requires heavy downloads on first run) and
feeds synthetic frames straight into the session tracker. Verifies that
rows land in the CSV with the right schema.

Run from the project root:

    python -m scripts.smoke_test
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import csv
import random

from app.analytics.csv_logger import reset_log
from app.analytics.session_tracker import get_session, reset_sessions
from app.config import CSV_COLUMNS, EMOTIONS_LOG_CSV


def main() -> None:
    reset_log()
    reset_sessions()
    random.seed(0)

    emotions = ["happy", "neutral", "sad", "surprise", "angry", "Absent"]
    students = ["S01", "S02", "S03"]
    lectures = ["L1_Test", "L2_Test"]

    for _ in range(60):
        s = random.choice(students)
        l = random.choice(lectures)
        e = random.choice(emotions)
        c = round(random.uniform(0.5, 0.99), 4) if e != "Absent" else 0.0
        get_session(s).process_frame(e, c, l)

    # Verify CSV
    with EMOTIONS_LOG_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    assert header == CSV_COLUMNS, f"Header mismatch: {header}"
    assert len(rows) == 60, f"Expected 60 rows, got {len(rows)}"

    # Spot-check schema integrity
    for row in rows[:5]:
        assert len(row) == len(CSV_COLUMNS)
        float(row[3])  # confidence parses
        float(row[5])  # engagement_score parses

    print(f"OK: {len(rows)} rows written to {EMOTIONS_LOG_CSV}")
    print(f"Header: {header}")
    print(f"First row: {rows[0]}")


if __name__ == "__main__":
    main()

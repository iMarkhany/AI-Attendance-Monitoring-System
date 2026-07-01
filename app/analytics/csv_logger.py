"""Append-only CSV logger.

This module is the bridge between the Python backend and the R Shiny
dashboard. Every analyzed frame is written as a row, and R simply tails
this file. Writes are guarded by a threading lock because FastAPI may
process multiple requests concurrently.

Schema is enforced by ``app.config.CSV_COLUMNS`` so the R side can rely
on column order and names being stable.
"""

import csv
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import CSV_COLUMNS, EMOTIONS_LOG_CSV

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()


def _ensure_header(path: Path) -> None:
    """Create the CSV with a header row if it doesn't already exist."""
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(CSV_COLUMNS)


def log_frame(
    *,
    student_id: str,
    emotion: str,
    confidence: float,
    lecture_id: str,
    engagement_score: float,
    timestamp: Optional[str] = None,
) -> str:
    """Append one analysis result to the persistent log.

    Returns the ISO-format timestamp that was written, so callers can echo
    it back to the client without computing it twice.
    """
    if timestamp is None:
        timestamp = datetime.now().isoformat(timespec="seconds")

    row = [
        student_id,
        timestamp,
        emotion,
        f"{confidence:.4f}",
        lecture_id,
        f"{engagement_score:.4f}",
    ]

    with _write_lock:
        _ensure_header(EMOTIONS_LOG_CSV)
        with EMOTIONS_LOG_CSV.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)
            f.flush()  # Make data visible to R immediately
    return timestamp


def reset_log() -> None:
    """Wipe the log file. Useful for tests and demo resets."""
    with _write_lock:
        if EMOTIONS_LOG_CSV.exists():
            EMOTIONS_LOG_CSV.unlink()
        _ensure_header(EMOTIONS_LOG_CSV)
    logger.info("Emotions log reset.")

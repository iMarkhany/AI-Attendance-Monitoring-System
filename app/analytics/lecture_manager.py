"""Lecture lifecycle management.

A "lecture" is a named time window during which student frames are
collected. Each lecture has a unique ID that gets stamped onto every
emotion record, which is what enables the R side to do per-lecture
statistical analysis and clustering.
"""

import csv
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.config import LECTURES_CSV

_lock = threading.Lock()
_active_lectures: Dict[str, dict] = {}

# Schema for the lectures CSV - separate from the frame log
_LECTURE_COLUMNS = [
    "lecture_id",
    "title",
    "lecturer_id",
    "started_at",
    "ended_at",
    "active",
]


def _ensure_header(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(_LECTURE_COLUMNS)


def _write_all(rows: List[dict]) -> None:
    """Rewrite the entire lectures CSV. Cheap because there are tens, not
    millions, of lectures."""
    with LECTURES_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_LECTURE_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _load_existing() -> List[dict]:
    if not LECTURES_CSV.exists():
        return []
    with LECTURES_CSV.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def start_lecture(
    lecture_id: Optional[str] = None,
    title: Optional[str] = None,
    lecturer_id: Optional[str] = None,
) -> dict:
    """Begin a new lecture. Returns the metadata dict."""
    with _lock:
        if lecture_id is None:
            lecture_id = f"L_{uuid.uuid4().hex[:8]}"

        info = {
            "lecture_id": lecture_id,
            "title": title or "",
            "lecturer_id": lecturer_id or "",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "ended_at": "",
            "active": "True",
        }
        _active_lectures[lecture_id] = info

        _ensure_header(LECTURES_CSV)
        existing = _load_existing()
        # Replace if same ID exists, otherwise append
        existing = [r for r in existing if r["lecture_id"] != lecture_id]
        existing.append(info)
        _write_all(existing)
        return info


def end_lecture(lecture_id: str) -> Optional[dict]:
    """Mark a lecture as ended. Returns the updated metadata or None."""
    with _lock:
        existing = _load_existing()
        for row in existing:
            if row["lecture_id"] == lecture_id:
                row["ended_at"] = datetime.now().isoformat(timespec="seconds")
                row["active"] = "False"
                _write_all(existing)
                _active_lectures.pop(lecture_id, None)
                return row
        return None


def list_lectures() -> List[dict]:
    """Return all known lectures, active and ended."""
    return _load_existing()


def is_active(lecture_id: str) -> bool:
    return lecture_id in _active_lectures

"""Generate synthetic but realistic-looking emotion data.

Use this to populate the CSV log when you don't have a webcam or
DeepFace installed yet. It writes directly via the same csv_logger the
backend uses, so the schema is guaranteed identical.

Run from the project root:

    python -m scripts.seed_data
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Allow running as a script or as a module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.analytics.csv_logger import log_frame, reset_log
from app.analytics import lecture_manager
from app.config import EMOTION_WEIGHTS

# Five lectures with intentionally varied engagement profiles so the
# clustering tabs in R have real signal to find.
LECTURE_PROFILES = {
    "L1_Algorithms":  {"lecturer": "lec_smith",  "mood": "engaged"},
    "L2_DistSecurity":{"lecturer": "lec_jones",  "mood": "mixed"},
    "L3_Forensics":   {"lecturer": "lec_smith",  "mood": "engaged"},
    "L4_Networks":    {"lecturer": "lec_lee",    "mood": "bored"},
    "L5_AI":          {"lecturer": "lec_jones",  "mood": "engaged"},
}

STUDENTS = [f"S{i:02d}" for i in range(1, 13)]

MOOD_DISTRIBUTIONS = {
    "engaged": {
        "happy": 0.45, "neutral": 0.30, "surprise": 0.15,
        "sad": 0.05, "angry": 0.02, "fear": 0.02, "disgust": 0.01,
    },
    "mixed": {
        "happy": 0.20, "neutral": 0.40, "surprise": 0.10,
        "sad": 0.15, "angry": 0.07, "fear": 0.05, "disgust": 0.03,
    },
    "bored": {
        "happy": 0.05, "neutral": 0.40, "surprise": 0.05,
        "sad": 0.30, "angry": 0.10, "fear": 0.05, "disgust": 0.05,
    },
}


def weighted_choice(distribution: dict[str, float]) -> str:
    emotions, weights = zip(*distribution.items())
    return random.choices(emotions, weights=weights, k=1)[0]


def simulate(frames_per_student_per_lecture: int = 60, ema_alpha: float = 0.3):
    reset_log()
    random.seed(7)
    base_time = datetime.now() - timedelta(days=14)

    for lec_idx, (lec_id, profile) in enumerate(LECTURE_PROFILES.items()):
        # Register lecture metadata
        lecture_manager.start_lecture(
            lecture_id=lec_id,
            title=lec_id.replace("_", " "),
            lecturer_id=profile["lecturer"],
        )
        lec_start = base_time + timedelta(days=lec_idx * 2)
        dist = MOOD_DISTRIBUTIONS[profile["mood"]]

        for student in STUDENTS:
            ema = 0.5
            for f in range(frames_per_student_per_lecture):
                # Most students follow the lecture mood, but sprinkle in
                # individuals who go against the grain so clustering has
                # something to discover.
                if student in ("S04", "S07") and profile["mood"] == "engaged":
                    chosen_dist = MOOD_DISTRIBUTIONS["bored"]
                elif student in ("S02", "S09") and profile["mood"] == "bored":
                    chosen_dist = MOOD_DISTRIBUTIONS["engaged"]
                else:
                    chosen_dist = dist

                # 5% chance of being absent for any given frame
                if random.random() < 0.05:
                    emotion = "Absent"
                    confidence = 0.0
                    raw = 0.0
                else:
                    emotion = weighted_choice(chosen_dist)
                    confidence = round(random.uniform(0.6, 0.99), 4)
                    raw = EMOTION_WEIGHTS.get(emotion, 0.5)

                ema = ema_alpha * raw + (1 - ema_alpha) * ema

                ts = (lec_start + timedelta(seconds=f * 10)).isoformat(
                    timespec="seconds"
                )
                log_frame(
                    student_id=student,
                    emotion=emotion,
                    confidence=confidence,
                    lecture_id=lec_id,
                    engagement_score=round(ema, 4),
                    timestamp=ts,
                )

        lecture_manager.end_lecture(lec_id)

    print(
        f"Seeded {len(LECTURE_PROFILES)} lectures × "
        f"{len(STUDENTS)} students × {frames_per_student_per_lecture} frames."
    )


if __name__ == "__main__":
    simulate()

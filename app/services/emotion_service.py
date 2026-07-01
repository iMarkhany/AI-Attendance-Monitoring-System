"""Wrapper around DeepFace emotion analysis."""

import logging
from typing import Dict

import numpy as np
from deepface import DeepFace

logger = logging.getLogger(__name__)


class EmotionService:
    """Stateless service that classifies the dominant emotion in a frame."""

    @staticmethod
    def analyze_face(frame: np.ndarray) -> Dict:
        """Run DeepFace emotion analysis with strict face detection.

        Returns a dict with ``emotion`` and ``confidence``. If no face is
        present, returns ``{"emotion": "Absent", "confidence": 0.0}``. Any
        other failure surfaces as ``{"emotion": "Error", "confidence": 0.0}``.
        """
        try:
            results = DeepFace.analyze(
                frame,
                actions=["emotion"],
                enforce_detection=True,
            )

            # DeepFace can return either a dict (single face) or a list.
            res = results[0] if isinstance(results, list) else results

            dominant = res["dominant_emotion"]
            confidence = float(res["emotion"][dominant]) / 100.0

            return {
                "emotion": dominant,
                "confidence": round(confidence, 4),
            }
        except ValueError:
            # DeepFace raises ValueError when enforce_detection finds no face
            return {"emotion": "Absent", "confidence": 0.0}
        except Exception as exc:  # noqa: BLE001
            logger.error("DeepFace processing error: %s", exc)
            return {"emotion": "Error", "confidence": 0.0}

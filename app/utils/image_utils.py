"""Decoding utilities for incoming image payloads."""

import base64

import cv2
import numpy as np


def decode_base64_image(base64_str: str) -> np.ndarray:
    """Decode a base64-encoded image into an OpenCV BGR ndarray.

    Accepts both raw base64 and data-URL form (``data:image/jpeg;base64,...``).
    Raises ``ValueError`` on any decoding failure so callers can surface a
    clean 400 response.
    """
    try:
        # Strip data-URL prefix if present
        if "," in base64_str:
            base64_str = base64_str.split(",", 1)[1]

        img_bytes = base64.b64decode(base64_str)
        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            raise ValueError("Decoded frame is empty.")
        return frame
    except Exception as exc:  # noqa: BLE001 — re-raised as ValueError below
        raise ValueError(f"Invalid image format: {exc}") from exc

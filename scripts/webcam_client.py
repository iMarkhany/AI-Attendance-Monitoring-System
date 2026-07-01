"""Webcam client for live demos.

Captures frames from the local webcam, base64-encodes them, and POSTs
them to the FastAPI ``/analyze`` endpoint. The returned engagement
score is overlaid on the live preview.

Usage:
    python -m scripts.webcam_client --student-id S01 --lecture-id L1_Demo

Press 'q' in the preview window to quit.
"""

from __future__ import annotations

import argparse
import base64
import time

import cv2
import requests


def encode_frame(frame) -> str:
    ok, buffer = cv2.imencode(".jpg", frame)
    if not ok:
        raise RuntimeError("Failed to encode frame as JPEG.")
    return base64.b64encode(buffer.tobytes()).decode("ascii")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--lecture-id", required=True)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="Seconds between API calls.")
    parser.add_argument("--camera", type=int, default=0,
                        help="OpenCV camera index.")
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise SystemExit(f"Could not open camera {args.camera}")

    last_call = 0.0
    last_result = {"emotion": "—", "engagement_score": 0.0,
                   "status": "—", "alert": None}

    print(f"Streaming → {args.api}/analyze "
          f"(student={args.student_id}, lecture={args.lecture_id})")
    print("Press 'q' to quit.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            now = time.time()
            if now - last_call >= args.interval:
                last_call = now
                try:
                    payload = {
                        "student_id": args.student_id,
                        "lecture_id": args.lecture_id,
                        "image_base64": encode_frame(frame),
                    }
                    resp = requests.post(
                        f"{args.api}/analyze", json=payload, timeout=10
                    )
                    if resp.ok:
                        last_result = resp.json()
                except requests.RequestException as exc:
                    last_result = {
                        "emotion": "ERR",
                        "engagement_score": 0.0,
                        "status": str(exc)[:40],
                        "alert": None,
                    }

            # Overlay
            text = (
                f"{last_result.get('emotion','-')} "
                f"| eng={last_result.get('engagement_score',0):.2f} "
                f"| {last_result.get('status','-')}"
            )
            colour = (0, 255, 0)
            if last_result.get("alert"):
                colour = (0, 0, 255)
                text += f" | {last_result['alert']}"

            cv2.putText(frame, text, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2)
            cv2.imshow("Engagement Webcam Client", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

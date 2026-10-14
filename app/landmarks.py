"""Face landmark detection with MediaPipe FaceLandmarker (Tasks API).

The model is loaded once and shared; MediaPipe calls are serialised with a
lock because a single landmarker instance is not safe for concurrent use.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class FaceObservation:
    landmarks: np.ndarray  # (478, 2) pixel coordinates of the tracked face
    face_count: int  # number of faces found in the frame


class LandmarkDetector(Protocol):
    def detect(self, rgb: np.ndarray) -> FaceObservation | None: ...


def _bbox_area(points: np.ndarray) -> float:
    width, height = points.max(axis=0) - points.min(axis=0)
    return float(width * height)


class MediaPipeLandmarkDetector:
    def __init__(self, model_path: str | Path, max_faces: int, min_confidence: float) -> None:
        model_path = Path(model_path)
        if not model_path.is_file():
            raise FileNotFoundError(f"Face landmarker model not found: {model_path}")

        # Imported here so modules that only need FaceObservation (and the unit
        # tests) don't require MediaPipe's native libraries.
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=max_faces,
            min_face_detection_confidence=min_confidence,
            min_face_presence_confidence=min_confidence,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._lock = threading.Lock()

    def detect(self, rgb: np.ndarray) -> FaceObservation | None:
        """Landmarks of the largest face in an RGB uint8 frame, or None if no face."""
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        with self._lock:
            result = self._landmarker.detect(image)
        if not result.face_landmarks:
            return None

        height, width = rgb.shape[:2]
        faces = [
            np.array([(p.x * width, p.y * height) for p in face], dtype=float)
            for face in result.face_landmarks
        ]
        # With several people in view, track the largest (usually closest) face.
        tracked = max(faces, key=_bbox_area)
        return FaceObservation(landmarks=tracked, face_count=len(faces))

    def close(self) -> None:
        with self._lock:
            self._landmarker.close()

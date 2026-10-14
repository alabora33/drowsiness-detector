"""Deterministic synthetic eye/face landmarks for tests."""

import cv2
import numpy as np

from app.metrics import LEFT_EYE, RIGHT_EYE


def synthetic_eye(width: float, opening: float, origin=(100.0, 50.0)) -> np.ndarray:
    """Six eye points p1..p6 with corners `width` apart and lids `opening` apart."""
    x, y = origin
    half = opening / 2
    return np.array(
        [
            (x, y),  # p1 outer corner
            (x + width / 3, y - half),  # p2 upper lid
            (x + 2 * width / 3, y - half),  # p3 upper lid
            (x + width, y),  # p4 inner corner
            (x + 2 * width / 3, y + half),  # p5 lower lid
            (x + width / 3, y + half),  # p6 lower lid
        ]
    )


def synthetic_face(ear: float, width: float = 30.0) -> np.ndarray:
    """478 face landmarks whose eyes both have the given EAR."""
    landmarks = np.zeros((478, 2))
    landmarks[:] = (150.0, 150.0)
    landmarks[list(LEFT_EYE)] = synthetic_eye(width, ear * width, origin=(200, 100))
    landmarks[list(RIGHT_EYE)] = synthetic_eye(width, ear * width, origin=(100, 100))
    return landmarks


def jpeg_bytes(width: int = 640, height: int = 480, value: int = 128) -> bytes:
    image = np.full((height, width, 3), value, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()

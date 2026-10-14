"""Eye aspect ratio (EAR), as defined by Soukupova & Cech (2016).

    EAR = (|p2 - p6| + |p3 - p5|) / (2 * |p1 - p4|)

p1/p4 are the eye corners, p2/p3 points on the upper lid and p6/p5 the
matching points on the lower lid. The ratio drops towards 0 as the eye
closes and is roughly independent of face size and distance to the camera.
"""

from __future__ import annotations

import numpy as np

# MediaPipe Face Mesh landmark indices, ordered p1..p6.
LEFT_EYE = (362, 385, 387, 263, 373, 380)
RIGHT_EYE = (33, 160, 158, 133, 153, 144)


def eye_aspect_ratio(eye: np.ndarray) -> float:
    """EAR for one eye given its six (x, y) points in pixel coordinates."""
    eye = np.asarray(eye, dtype=float)
    if eye.shape != (6, 2):
        raise ValueError(f"expected 6 (x, y) eye points, got shape {eye.shape}")
    p1, p2, p3, p4, p5, p6 = eye
    width = np.linalg.norm(p1 - p4)
    if width < 1e-6:
        raise ValueError("degenerate eye: corner points coincide")
    height = np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)
    return float(height / (2.0 * width))


def mean_eye_aspect_ratio(landmarks: np.ndarray) -> float:
    """Average EAR of both eyes from a face's landmarks, shape (N, 2) in pixels.

    Landmarks must be in pixel units: MediaPipe's normalised coordinates
    scale x and y by different amounts on non-square frames, which would
    distort the ratio.
    """
    landmarks = np.asarray(landmarks, dtype=float)
    left = eye_aspect_ratio(landmarks[list(LEFT_EYE)])
    right = eye_aspect_ratio(landmarks[list(RIGHT_EYE)])
    return (left + right) / 2.0

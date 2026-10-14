import numpy as np
import pytest

from app.metrics import LEFT_EYE, RIGHT_EYE, eye_aspect_ratio, mean_eye_aspect_ratio


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


def test_ear_open_eye():
    # opening 9 over width 30 -> (9 + 9) / (2 * 30) = 0.3
    assert eye_aspect_ratio(synthetic_eye(30, 9)) == pytest.approx(0.3)


def test_ear_closed_eye_is_zero():
    assert eye_aspect_ratio(synthetic_eye(30, 0)) == pytest.approx(0.0)


def test_ear_is_scale_invariant():
    near = eye_aspect_ratio(synthetic_eye(60, 15))
    far = eye_aspect_ratio(synthetic_eye(20, 5))
    assert near == pytest.approx(far)


def test_ear_rejects_degenerate_eye():
    eye = np.zeros((6, 2))
    with pytest.raises(ValueError, match="degenerate"):
        eye_aspect_ratio(eye)


def test_ear_rejects_wrong_shape():
    with pytest.raises(ValueError, match="6"):
        eye_aspect_ratio(np.zeros((5, 2)))


def test_mean_ear_uses_mediapipe_indices():
    landmarks = np.zeros((478, 2))
    landmarks[list(LEFT_EYE)] = synthetic_eye(30, 9)  # 0.3
    landmarks[list(RIGHT_EYE)] = synthetic_eye(30, 3, origin=(200, 50))  # 0.1
    assert mean_eye_aspect_ratio(landmarks) == pytest.approx(0.2)

"""Runs the real MediaPipe model on a real photo (needs MediaPipe's native libs)."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.landmarks import MediaPipeLandmarkDetector
from app.metrics import mean_eye_aspect_ratio

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def landmarker():
    detector = MediaPipeLandmarkDetector(
        ROOT / "models/face_landmarker.task", max_faces=2, min_confidence=0.5
    )
    yield detector
    detector.close()


def load_rgb(path: Path, width: int = 640) -> np.ndarray:
    bgr = cv2.imread(str(path))
    height = round(bgr.shape[0] * width / bgr.shape[1])
    return cv2.cvtColor(cv2.resize(bgr, (width, height)), cv2.COLOR_BGR2RGB)


def test_detects_face_and_plausible_ear(landmarker):
    observation = landmarker.detect(load_rgb(ROOT / "tests/fixtures/portrait.jpg"))
    assert observation is not None
    assert observation.face_count == 1
    assert observation.landmarks.shape == (478, 2)
    # Open but smiling eyes: ~0.20. Closed eyes are typically below ~0.12.
    assert 0.15 < mean_eye_aspect_ratio(observation.landmarks) < 0.35


def test_blank_frame_has_no_face(landmarker):
    assert landmarker.detect(np.zeros((480, 640, 3), dtype=np.uint8)) is None


def test_missing_model_fails_clearly(tmp_path):
    with pytest.raises(FileNotFoundError, match="model not found"):
        MediaPipeLandmarkDetector(tmp_path / "missing.task", max_faces=1, min_confidence=0.5)

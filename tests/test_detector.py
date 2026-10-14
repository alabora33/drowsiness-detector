from pathlib import Path

import pytest

from app.config import DetectionConfig, load_config
from app.detector import DrowsinessDetector, State

OPEN = 0.30
CLOSED = 0.10
DEFAULTS = load_config(Path(__file__).resolve().parents[1] / "configs/default.yaml").detection


def make_config(perclos_enabled: bool = False, **overrides) -> DetectionConfig:
    """Default detection config; PERCLOS off unless a test is about PERCLOS."""
    perclos = DEFAULTS.perclos.model_copy(update={"enabled": perclos_enabled})
    return DEFAULTS.model_copy(update={"perclos": perclos, **overrides})


def feed(detector, ear, start, end, fps):
    """Feed a constant EAR from `start` to `end` seconds; return the last result."""
    result = None
    step = 1.0 / fps
    t = start
    while t <= end + 1e-9:
        result = detector.update(ear, now=t)
        t += step
    return result


@pytest.fixture
def detector():
    return DrowsinessDetector(make_config(), alerts_enabled=True)


def test_open_eyes_are_awake(detector):
    result = feed(detector, OPEN, 0, 2, fps=10)
    assert result.state is State.AWAKE
    assert result.closed_seconds == 0
    assert result.alert is False


def test_normal_blink_does_not_warn(detector):
    feed(detector, OPEN, 0, 1, fps=10)
    blink = feed(detector, CLOSED, 1.1, 1.3, fps=10)
    assert blink.state is State.EYES_CLOSED
    # The blink only ends after the eyes stay open for min_open_seconds (0.2 s).
    assert detector.update(OPEN, now=1.5).state is State.EYES_CLOSED
    after = detector.update(OPEN, now=1.75)
    assert after.state is State.AWAKE
    assert after.closed_seconds == 0


def test_prolonged_closure_warns_after_min_closed_seconds(detector):
    feed(detector, OPEN, 0, 1, fps=10)
    almost = feed(detector, CLOSED, 1.1, 2.5, fps=10)  # closed for 1.4 s
    assert almost.state is State.EYES_CLOSED
    assert almost.alert is False
    warning = detector.update(CLOSED, now=2.6)  # closed for 1.5 s
    assert warning.state is State.DROWSINESS_WARNING
    assert warning.closed_seconds == pytest.approx(1.5)
    assert warning.alert is True


def test_genuine_reopening_is_recognized_after_min_open_seconds(detector):
    assert feed(detector, CLOSED, 0, 2, fps=4).state is State.DROWSINESS_WARNING
    # First open frame: could be noise, the warning is held.
    held = detector.update(OPEN, now=2.25)
    assert held.state is State.DROWSINESS_WARNING
    assert held.alert is True
    # Open for 0.25 s >= min_open_seconds (0.2 s): recognized on the next frame.
    reopened = detector.update(OPEN, now=2.5)
    assert reopened.state is State.AWAKE
    assert reopened.alert is False
    assert reopened.closed_seconds == 0
    # A new closure starts counting from zero again.
    assert detector.update(CLOSED, now=2.75).closed_seconds == 0


def test_isolated_noisy_frames_do_not_reset_closure(detector):
    """Regression: 3 s of closed eyes with two noisy 'open' frames must still warn."""
    ears = [CLOSED] * 30  # 10 fps
    ears[10] = ears[22] = DEFAULTS.ear_threshold + 0.01  # just above the threshold
    results = [detector.update(ear, now=i / 10) for i, ear in enumerate(ears)]
    assert all(r.state is not State.AWAKE for r in results)
    assert results[15].state is State.DROWSINESS_WARNING  # at 1.5 s
    assert all(r.state is State.DROWSINESS_WARNING for r in results[15:])
    assert results[-1].closed_seconds == pytest.approx(2.9)


def test_noise_burst_shorter_than_min_open_seconds_is_ignored_at_30_fps(detector):
    feed(detector, CLOSED, 0, 1.0, fps=30)
    for i in range(1, 4):  # three consecutive open frames spanning ~0.07 s
        detector.update(OPEN, now=1.0 + i / 30)
    result = feed(detector, CLOSED, 1.2, 1.6, fps=30)
    assert result.state is State.DROWSINESS_WARNING
    # The episode started at 0 s: the noise burst did not restart the timer.
    assert result.closed_seconds > 1.5


def test_min_open_seconds_zero_ends_closure_on_first_open_frame():
    detector = DrowsinessDetector(make_config(min_open_seconds=0), alerts_enabled=True)
    feed(detector, CLOSED, 0, 1, fps=10)
    assert detector.update(OPEN, now=1.1).state is State.AWAKE


@pytest.mark.parametrize("fps", [2, 5, 30])
def test_warning_depends_on_time_not_frame_count(fps):
    detector = DrowsinessDetector(make_config(), alerts_enabled=True)
    assert feed(detector, CLOSED, 0, 1.0, fps).state is State.EYES_CLOSED
    assert feed(detector, CLOSED, 1.0 + 1 / fps, 2.0, fps).state is State.DROWSINESS_WARNING


def test_ear_exactly_at_threshold_counts_as_open(detector):
    assert detector.update(DEFAULTS.ear_threshold, now=0).state is State.AWAKE


def test_no_face_from_start(detector):
    result = detector.update(None, now=0)
    assert result.state is State.NO_FACE_DETECTED
    assert result.ear is None
    assert result.face_count == 0


def test_short_face_loss_keeps_state_and_closure_keeps_counting(detector):
    feed(detector, CLOSED, 0, 1.0, fps=10)
    dropout = feed(detector, None, 1.1, 1.6, fps=10)  # 0.6 s gap < 1.0 s grace
    assert dropout.state is State.DROWSINESS_WARNING
    assert dropout.closed_seconds == pytest.approx(1.6)


def test_long_face_loss_reports_no_face_and_resets_closure(detector):
    feed(detector, CLOSED, 0, 1.0, fps=10)
    gone = feed(detector, None, 1.1, 2.5, fps=10)
    assert gone.state is State.NO_FACE_DETECTED
    assert gone.alert is False
    back = detector.update(CLOSED, now=2.6)
    assert back.state is State.EYES_CLOSED
    assert back.closed_seconds == 0


def test_alerts_disabled_never_alert():
    detector = DrowsinessDetector(make_config(), alerts_enabled=False)
    result = feed(detector, CLOSED, 0, 3, fps=10)
    assert result.state is State.DROWSINESS_WARNING
    assert result.alert is False


def test_perclos_disabled_is_none(detector):
    assert feed(detector, OPEN, 0, 40, fps=5).perclos is None


def test_perclos_waits_for_window_coverage():
    detector = DrowsinessDetector(make_config(perclos_enabled=True), alerts_enabled=True)
    window = DEFAULTS.perclos.window_seconds
    assert feed(detector, OPEN, 0, window * 0.4, fps=5).perclos is None
    assert feed(detector, OPEN, window * 0.4 + 0.2, window * 0.6, fps=5).perclos == 0


def test_frequent_short_closures_trigger_perclos_warning():
    """Long, frequent blinks never reach min_closed_seconds but PERCLOS catches them."""
    detector = DrowsinessDetector(make_config(perclos_enabled=True), alerts_enabled=True)
    t = 0.0
    result = None
    while t < 30:
        # 1 s open, 0.8 s closed -> ~44% closed, above the 30% threshold.
        result = feed(detector, OPEN, t, t + 1.0, fps=10)
        result = feed(detector, CLOSED, t + 1.1, t + 1.8, fps=10)
        t += 1.9
    assert result.closed_seconds < DEFAULTS.min_closed_seconds
    assert result.perclos > DEFAULTS.perclos.threshold
    assert result.state is State.DROWSINESS_WARNING
    # Even with eyes open, the recent history still warns.
    assert detector.update(OPEN, now=t).state is State.DROWSINESS_WARNING


def test_perclos_ignores_long_gaps_between_frames():
    detector = DrowsinessDetector(make_config(perclos_enabled=True), alerts_enabled=True)
    feed(detector, OPEN, 0, 14, fps=5)
    detector.update(CLOSED, now=14.2)
    # 10 s with no frames (e.g. hidden tab) must not count as 10 s of closed eyes.
    result = feed(detector, OPEN, 24.2, 26, fps=5)
    assert result.perclos < 0.1

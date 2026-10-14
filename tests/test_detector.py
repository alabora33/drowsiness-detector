from pathlib import Path

import pytest

from app.config import DetectionConfig, load_config
from app.detector import DrowsinessDetector, State, WarningReason

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


# --- Warning reasons -------------------------------------------------------
# Times use 0.25 s steps (4 fps) so they are exact in binary floating point.

CONTINUOUS = WarningReason.CONTINUOUS_CLOSURE
PERCLOS = WarningReason.PERCLOS


def test_continuous_closure_warning_reason(detector):
    almost = feed(detector, CLOSED, 0, 1.25, fps=4)
    assert almost.state is State.EYES_CLOSED
    assert almost.warning_reasons == ()
    warning = detector.update(CLOSED, now=1.5)
    assert warning.state is State.DROWSINESS_WARNING
    assert warning.warning_reasons == (CONTINUOUS,)


def test_perclos_triggers_warning_while_current_closure_is_short():
    """The real-webcam case: warnings at closed=0.40 s / 0.87 s came from PERCLOS."""
    detector = DrowsinessDetector(make_config(perclos_enabled=True), alerts_enabled=True)
    results = []
    t = 0.0
    while t < 25:
        # 1 s closed, 1.5 s open: ~40 % closed, no closure reaches 1.5 s.
        results.append(feed(detector, CLOSED, t, t + 0.75, fps=4))
        results.append(feed(detector, OPEN, t + 1.0, t + 2.25, fps=4))
        t += 2.5
    warnings = [r for r in results if r.state is State.DROWSINESS_WARNING]
    assert warnings
    for result in warnings:
        assert result.closed_seconds < DEFAULTS.min_closed_seconds
        assert result.warning_reasons == (PERCLOS,)


def closure_after_open_history(detector):
    """10 s open, then 6 s closed: PERCLOS = 6/16 = 0.375 at the end of the closure."""
    feed(detector, OPEN, 0, 9.75, fps=4)
    return feed(detector, CLOSED, 10, 16, fps=4)


def test_both_warning_reasons_can_be_active_at_once():
    detector = DrowsinessDetector(make_config(perclos_enabled=True), alerts_enabled=True)
    result = closure_after_open_history(detector)
    assert result.state is State.DROWSINESS_WARNING
    assert result.closed_seconds == 6.0
    assert result.perclos == 0.375
    assert result.warning_reasons == (CONTINUOUS, PERCLOS)


def test_closure_warning_is_held_by_perclos_after_eyes_reopen():
    detector = DrowsinessDetector(make_config(perclos_enabled=True), alerts_enabled=True)
    closure_after_open_history(detector)
    # Eyes open for 0.25 s >= min_open_seconds: the closure itself has ended ...
    reopened = feed(detector, OPEN, 16.25, 16.5, fps=4)
    assert reopened.closed_seconds == 0
    # ... but the recent history still warns, now only because of PERCLOS.
    assert reopened.state is State.DROWSINESS_WARNING
    assert reopened.warning_reasons == (PERCLOS,)
    assert reopened.alert is True
    # Once PERCLOS drops below 0.3 (6 s closed / > 20 s observed) it is AWAKE again.
    recovered = feed(detector, OPEN, 16.75, 21, fps=4)
    assert recovered.state is State.AWAKE
    assert recovered.warning_reasons == ()


def test_warning_reason_is_kept_during_short_face_loss(detector):
    feed(detector, CLOSED, 0, 1.5, fps=4)
    dropout = detector.update(None, now=1.75)
    assert dropout.state is State.DROWSINESS_WARNING
    assert dropout.warning_reasons == (CONTINUOUS,)


def test_warning_reasons_serialize_as_strings():
    detector = DrowsinessDetector(make_config(perclos_enabled=True), alerts_enabled=True)
    data = closure_after_open_history(detector).to_dict()
    assert data["state"] == "DROWSINESS_WARNING"
    assert data["warning_reasons"] == ["continuous_closure", "perclos"]
    awake = DrowsinessDetector(make_config(), alerts_enabled=True).update(OPEN, now=0)
    assert awake.to_dict()["warning_reasons"] == []

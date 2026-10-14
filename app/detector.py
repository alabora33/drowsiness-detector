"""Temporal drowsiness logic: turns per-frame EAR values into a state.

All durations use the caller-supplied timestamp (seconds, monotonic), never
frame counts, so behaviour is the same at 5 fps and at 30 fps.

A closure ("episode") starts at the first frame with EAR below the threshold
and only ends once the eyes have stayed open for `min_open_seconds`. Single
noisy frames during a long closure therefore don't restart the timer.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import asdict, dataclass
from enum import StrEnum

from app.config import DetectionConfig

logger = logging.getLogger(__name__)

# PERCLOS is only reported once this fraction of its window has data, so a
# single blink right after start-up doesn't read as "100% closed".
PERCLOS_MIN_COVERAGE = 0.5
# A longer gap between two frames (hidden tab, network stall) is not
# attributed to the earlier frame's eye state.
MAX_SAMPLE_GAP_SECONDS = 1.0


class State(StrEnum):
    AWAKE = "AWAKE"
    EYES_CLOSED = "EYES_CLOSED"
    DROWSINESS_WARNING = "DROWSINESS_WARNING"
    NO_FACE_DETECTED = "NO_FACE_DETECTED"


@dataclass(frozen=True)
class DetectionResult:
    state: State
    ear: float | None
    closed_seconds: float
    perclos: float | None
    face_count: int
    alert: bool

    def to_dict(self) -> dict:
        data = asdict(self)
        data["state"] = self.state.value
        return data


class DrowsinessDetector:
    """Per-session state machine. Create one per camera stream."""

    def __init__(self, config: DetectionConfig, alerts_enabled: bool) -> None:
        self._cfg = config
        self._alerts_enabled = alerts_enabled
        self._closed_since: float | None = None  # start of the current closure episode
        self._open_since: float | None = None  # first open frame within that episode
        self._last_face_at: float | None = None
        self._state = State.NO_FACE_DETECTED
        self._samples: deque[tuple[float, bool]] = deque()  # (timestamp, eyes_closed)

    def update(self, ear: float | None, now: float, face_count: int = 1) -> DetectionResult:
        """Feed one frame's mean EAR (None when no face was found) taken at time `now`."""
        if ear is None:
            return self._update_without_face(now)

        self._last_face_at = now
        closed = ear < self._cfg.ear_threshold
        # PERCLOS uses the raw per-frame measurement, without noise filtering.
        self._record_sample(now, closed)

        if closed:
            if self._closed_since is None:
                self._closed_since = now
            self._open_since = None
        elif self._closed_since is not None:
            # Eyes look open during a closure: only end it once they have
            # stayed open for min_open_seconds (filters isolated noisy frames).
            if self._open_since is None:
                self._open_since = now
            if now - self._open_since >= self._cfg.min_open_seconds:
                self._closed_since = None
                self._open_since = None

        in_closure = self._closed_since is not None
        closed_seconds = now - self._closed_since if in_closure else 0.0

        perclos = self._perclos()
        if closed_seconds >= self._cfg.min_closed_seconds or self._perclos_exceeded(perclos):
            state = State.DROWSINESS_WARNING
        elif in_closure:
            state = State.EYES_CLOSED
        else:
            state = State.AWAKE
        return self._result(state, ear, closed_seconds, perclos, face_count)

    def _update_without_face(self, now: float) -> DetectionResult:
        in_grace = (
            self._last_face_at is not None
            and now - self._last_face_at <= self._cfg.no_face_grace_seconds
        )
        if in_grace:
            # Brief tracking loss (head turn, motion blur): keep the last eye
            # state, and let a running eye closure keep counting.
            closed_seconds = 0.0 if self._closed_since is None else now - self._closed_since
            state = self._state
            if closed_seconds >= self._cfg.min_closed_seconds:
                state = State.DROWSINESS_WARNING
            return self._result(state, None, closed_seconds, self._perclos(), 0)

        self._closed_since = None
        self._open_since = None
        return self._result(State.NO_FACE_DETECTED, None, 0.0, None, 0)

    def _record_sample(self, now: float, closed: bool) -> None:
        self._samples.append((now, closed))
        horizon = now - self._cfg.perclos.window_seconds
        while self._samples and self._samples[0][0] < horizon:
            self._samples.popleft()

    def _perclos(self) -> float | None:
        """Time-weighted fraction of the window during which the eyes were closed."""
        if not self._cfg.perclos.enabled or len(self._samples) < 2:
            return None
        closed_time = observed_time = 0.0
        samples = list(self._samples)
        for (t0, closed), (t1, _) in zip(samples, samples[1:], strict=False):
            dt = min(t1 - t0, MAX_SAMPLE_GAP_SECONDS)
            observed_time += dt
            if closed:
                closed_time += dt
        if observed_time < self._cfg.perclos.window_seconds * PERCLOS_MIN_COVERAGE:
            return None
        return closed_time / observed_time

    def _perclos_exceeded(self, perclos: float | None) -> bool:
        return perclos is not None and perclos >= self._cfg.perclos.threshold

    def _result(
        self,
        state: State,
        ear: float | None,
        closed_seconds: float,
        perclos: float | None,
        face_count: int,
    ) -> DetectionResult:
        if state is not self._state:
            logger.info(
                "State %s -> %s (ear=%s, closed=%.2fs)",
                self._state,
                state,
                ear and round(ear, 3),
                closed_seconds,
            )
            self._state = state
        return DetectionResult(
            state=state,
            ear=ear,
            closed_seconds=round(closed_seconds, 3),
            perclos=None if perclos is None else round(perclos, 3),
            face_count=face_count,
            alert=self._alerts_enabled and state is State.DROWSINESS_WARNING,
        )

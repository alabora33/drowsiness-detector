"""Decoding and validation of frames received from the browser."""

from __future__ import annotations

import cv2
import numpy as np

# Generous for a 640x480 JPEG (~30-80 KB); protects the decoder from huge payloads.
MAX_FRAME_BYTES = 2_000_000
MIN_FRAME_SIDE = 32


class FrameError(ValueError):
    """The received payload is not a usable frame. Reported to the client, not fatal."""


def decode_frame(data: bytes, max_width: int) -> np.ndarray:
    """Decode a JPEG/PNG payload into an RGB uint8 array no wider than `max_width`."""
    if not data:
        raise FrameError("empty frame")
    if len(data) > MAX_FRAME_BYTES:
        raise FrameError(f"frame too large: {len(data)} bytes (limit {MAX_FRAME_BYTES})")

    bgr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise FrameError("frame is not a decodable image")

    height, width = bgr.shape[:2]
    if min(height, width) < MIN_FRAME_SIDE:
        raise FrameError(f"frame too small: {width}x{height}")
    if width > max_width:
        new_height = round(height * max_width / width)
        bgr = cv2.resize(bgr, (max_width, new_height), interpolation=cv2.INTER_AREA)

    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def mean_brightness(rgb: np.ndarray) -> float:
    """Average luma (0-255), used to tell "too dark" apart from "no face"."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return float(gray.mean())

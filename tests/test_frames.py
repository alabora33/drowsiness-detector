import pytest

from app.frames import MAX_FRAME_BYTES, FrameError, decode_frame, mean_brightness
from tests.synthetic import jpeg_bytes


def test_decodes_jpeg_to_rgb():
    rgb = decode_frame(jpeg_bytes(320, 240), max_width=640)
    assert rgb.shape == (240, 320, 3)
    assert rgb.dtype.name == "uint8"


def test_downscales_wide_frames_keeping_aspect_ratio():
    rgb = decode_frame(jpeg_bytes(1280, 720), max_width=640)
    assert rgb.shape == (360, 640, 3)


def test_empty_frame():
    with pytest.raises(FrameError, match="empty"):
        decode_frame(b"", max_width=640)


def test_garbage_bytes():
    with pytest.raises(FrameError, match="not a decodable image"):
        decode_frame(b"definitely not a jpeg", max_width=640)


def test_oversized_payload():
    with pytest.raises(FrameError, match="too large"):
        decode_frame(b"\xff" * (MAX_FRAME_BYTES + 1), max_width=640)


def test_tiny_frame():
    with pytest.raises(FrameError, match="too small"):
        decode_frame(jpeg_bytes(16, 16), max_width=640)


def test_brightness():
    assert mean_brightness(decode_frame(jpeg_bytes(value=10), 640)) < 20
    assert mean_brightness(decode_frame(jpeg_bytes(value=200), 640)) > 180

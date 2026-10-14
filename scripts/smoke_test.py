"""End-to-end smoke test against a running server (local process or container).

Exercises the same path as the browser: HTTP health/page, then WebSocket
frames through the real MediaPipe model.

    python scripts/smoke_test.py --url http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np
from websockets.asyncio.client import connect

PORTRAIT = Path(__file__).resolve().parents[1] / "tests/fixtures/portrait.jpg"


def wait_for_health(base_url: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2) as response:
                return json.load(response)
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def encode_jpeg(image: np.ndarray) -> bytes:
    ok, data = cv2.imencode(".jpg", image)
    assert ok
    return data.tobytes()


def check(condition: bool, description: str) -> None:
    print(("PASS " if condition else "FAIL ") + description)
    if not condition:
        raise SystemExit(1)


async def run_websocket_checks(ws_url: str) -> None:
    portrait = cv2.imread(str(PORTRAIT))
    async with connect(ws_url, max_size=2**20) as ws:
        config = json.loads(await ws.recv())
        check(config["type"] == "config", f"websocket sends client config ({config['camera']})")

        await ws.send(encode_jpeg(portrait))
        result = json.loads(await ws.recv())
        check(result["type"] == "result", "real photo returns a result")
        check(result["face_count"] == 1, f"face detected (face_count={result['face_count']})")
        check(result["ear"] is not None, f"EAR computed (ear={result['ear']})")
        print(f"     state={result['state']} processing_ms={result['processing_ms']}")

        await ws.send(b"garbage")
        error = json.loads(await ws.recv())
        check(error["type"] == "error", f"invalid frame rejected ({error['message']})")

        await asyncio.sleep(2)  # longer than any configured no-face grace period
        await ws.send(encode_jpeg(np.zeros((480, 640, 3), np.uint8)))
        blank = json.loads(await ws.recv())
        check(blank["state"] == "NO_FACE_DETECTED", "blank frame -> NO_FACE_DETECTED")
        check(blank["low_light"] is True, "black frame flagged as low light")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    base_url = args.url.rstrip("/")

    health = wait_for_health(base_url, args.timeout)
    check(health["status"] == "ok", f"/health ok (version {health['version']})")
    with urllib.request.urlopen(base_url + "/", timeout=5) as response:
        check("getUserMedia" in response.read().decode(), "camera page served at /")

    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
    asyncio.run(run_websocket_checks(ws_url))
    print("Smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

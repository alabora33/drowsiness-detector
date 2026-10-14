"""HTTP/WebSocket API.

The browser captures the camera, sends JPEG frames over /ws and gets one JSON
result back per frame. The client waits for each result before sending the
next frame, so a slow server lowers the frame rate instead of building a queue.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.config import AppConfig
from app.detector import DrowsinessDetector
from app.frames import FrameError, decode_frame, mean_brightness
from app.landmarks import LandmarkDetector
from app.metrics import mean_eye_aspect_ratio

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def process_frame(
    data: bytes,
    received_at: float,
    config: AppConfig,
    landmarks: LandmarkDetector,
    detector: DrowsinessDetector,
) -> dict:
    """Run one frame through the pipeline and return the JSON-ready result."""
    started = time.perf_counter()
    rgb = decode_frame(data, max_width=config.camera.frame_width)
    observation = landmarks.detect(rgb)

    ear = None
    face_count = 0
    if observation is not None:
        face_count = observation.face_count
        try:
            ear = mean_eye_aspect_ratio(observation.landmarks)
        except ValueError:
            logger.debug("Degenerate eye landmarks; treating frame as having no face")

    result = detector.update(ear, now=received_at, face_count=face_count)
    payload = result.to_dict()
    if payload["ear"] is not None:
        payload["ear"] = round(payload["ear"], 3)
    payload["low_light"] = mean_brightness(rgb) < config.detection.low_light_threshold
    payload["processing_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return payload


def create_app(
    config: AppConfig,
    landmarks: LandmarkDetector,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    app = FastAPI(title="drowsiness-detector", version=__version__)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.websocket("/ws")
    async def stream(websocket: WebSocket) -> None:
        await websocket.accept()
        client = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "?"
        logger.info("Client connected: %s", client)
        detector = DrowsinessDetector(config.detection, alerts_enabled=config.alerts.enabled)
        await websocket.send_json(
            {
                "type": "config",
                "version": __version__,
                "camera": config.camera.model_dump(),
                "alerts": config.alerts.model_dump(),
            }
        )
        frames = 0
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                received_at = clock()
                data = message.get("bytes")
                if data is None:
                    await websocket.send_json(
                        {"type": "error", "message": "expected a binary JPEG frame"}
                    )
                    continue
                try:
                    payload = await run_in_threadpool(
                        process_frame, data, received_at, config, landmarks, detector
                    )
                except FrameError as exc:
                    logger.warning("Rejected frame from %s: %s", client, exc)
                    await websocket.send_json({"type": "error", "message": str(exc)})
                    continue
                frames += 1
                await websocket.send_json({"type": "result", **payload})
        except WebSocketDisconnect:
            pass
        finally:
            logger.info("Client disconnected: %s (%d frames)", client, frames)

    return app

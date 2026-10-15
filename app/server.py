from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.config import AppConfig
from app.config_manager import ConfigManager
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

    config_manager = ConfigManager(
        config,
        settings_path=os.environ.get("APP_SETTINGS_PATH"),
    )

    @app.get("/api/settings")
    def get_settings() -> dict:
        current = config_manager.get_config()

        return {
            "detection": current.detection.model_dump(
                exclude={"model_path", "max_faces", "min_face_confidence"}
            ),
            "alerts": {
                "sound": current.alerts.sound,
            },
        }

    @app.patch("/api/settings")
    def update_settings(changes: dict) -> dict:
        if not os.environ.get("APP_SETTINGS_PATH"):
            raise HTTPException(
                status_code=503,
                detail="Kalıcı ayar dosyası yapılandırılmamış.",
            )

        try:
            current = config_manager.update_detection(changes)

        except (ValidationError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

        except OSError as exc:
            logger.exception("Ayarlar kaydedilemedi")
            raise HTTPException(
                status_code=500,
                detail="Ayarlar dosyaya kaydedilemedi.",
            ) from exc

        return {
            "message": "Ayarlar kaydedildi.",
            "detection": current.detection.model_dump(),
            "config_version": config_manager.get_snapshot()[1],
        }

    @app.post("/api/settings/reset")
    def reset_settings() -> dict:
        if not os.environ.get("APP_SETTINGS_PATH"):
            raise HTTPException(
                status_code=503,
                detail="Kalıcı ayar dosyası yapılandırılmamış.",
            )

        try:
            current = config_manager.reset()

        except OSError as exc:
            logger.exception("Ayarlar sıfırlanamadı")
            raise HTTPException(
                status_code=500,
                detail="Ayarlar sıfırlanamadı.",
            ) from exc

        return {
            "message": "Başlangıç ayarlarına dönüldü.",
            "detection": current.detection.model_dump(),
            "config_version": config_manager.get_snapshot()[1],
        }

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
        active_config, active_version = config_manager.get_snapshot()

        detector = DrowsinessDetector(
            active_config.detection,
            alerts_enabled=active_config.alerts.enabled,
        )

        await websocket.send_json(
            {
                "type": "config",
                "version": __version__,
                "camera": active_config.camera.model_dump(),
                "alerts": active_config.alerts.model_dump(),
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
                    current_config, current_version = config_manager.get_snapshot()

                    if current_version != active_version:
                        detector = DrowsinessDetector(
                            current_config.detection,
                            alerts_enabled=current_config.alerts.enabled,
                        )
                        active_version = current_version
                        logger.info(
                            "Detection settings updated to version %d",
                            active_version,
                        )

                    active_config = current_config

                    payload = await run_in_threadpool(
                        process_frame,
                        data,
                        received_at,
                        active_config,
                        landmarks,
                        detector,
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

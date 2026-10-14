"""Entry point: `python -m app.main` (or `--healthcheck` for container health probes)."""

from __future__ import annotations

import argparse
import logging
import sys
import urllib.request

from app import __version__
from app.config import AppConfig, ConfigError, load_config, resolve_config_path

logger = logging.getLogger("app")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def healthcheck(config: AppConfig) -> int:
    url = f"http://127.0.0.1:{config.server.port}/health"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return 0 if response.status == 200 else 1
    except OSError:
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Drowsiness detection server")
    parser.add_argument("--healthcheck", action="store_true", help="probe /health and exit")
    args = parser.parse_args(argv)

    config_path = resolve_config_path()
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 2

    if args.healthcheck:
        return healthcheck(config)

    configure_logging(config.logging.level)
    logger.info("drowsiness-detector %s, config %s", __version__, config_path)

    # Imported after config validation so a bad config fails fast and clearly.
    import uvicorn

    from app.landmarks import MediaPipeLandmarkDetector
    from app.server import create_app

    try:
        landmarks = MediaPipeLandmarkDetector(
            config.detection.model_path,
            max_faces=config.detection.max_faces,
            min_confidence=config.detection.min_face_confidence,
        )
    except FileNotFoundError as exc:
        logger.error("Startup failed: %s", exc)
        return 2
    except OSError as exc:
        logger.error(
            "Startup failed: cannot load MediaPipe native libraries (%s). "
            "On Debian install them with: sudo apt install libgles2 libegl1",
            exc,
        )
        return 2

    app = create_app(config, landmarks)
    try:
        uvicorn.run(
            app,
            host=config.server.host,
            port=config.server.port,
            log_level=config.logging.level.lower(),
            ws="websockets-sansio",
        )
    finally:
        landmarks.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

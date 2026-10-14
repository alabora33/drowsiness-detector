"""Application configuration: YAML file -> validated, immutable settings.

Every value must be present in the YAML file. Defaults live in
``configs/default.yaml`` rather than in code, so a config file is always a
complete, readable description of how the service behaves.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONFIG_ENV_VAR = "APP_CONFIG"
DEFAULT_CONFIG_PATH = Path("configs/default.yaml")


class ConfigError(Exception):
    """Raised when a configuration file is missing, malformed or invalid."""


class _Section(BaseModel):
    # Unknown keys are rejected so a typo like "ear_treshold" fails loudly
    # instead of silently falling back to some other value.
    model_config = ConfigDict(extra="forbid", frozen=True)


class ServerConfig(_Section):
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)


class CameraConfig(_Section):
    """Capture settings sent to the browser client."""

    max_fps: float = Field(gt=0, le=30)
    frame_width: int = Field(ge=160, le=1920)
    frame_height: int = Field(ge=120, le=1080)
    jpeg_quality: float = Field(ge=0.3, le=1.0)


class PerclosConfig(_Section):
    enabled: bool
    window_seconds: float = Field(ge=5, le=300)
    threshold: float = Field(gt=0, lt=1)


class DetectionConfig(_Section):
    model_path: str = Field(min_length=1)
    max_faces: int = Field(ge=1, le=5)
    min_face_confidence: float = Field(ge=0, le=1)
    ear_threshold: float = Field(ge=0.05, le=0.4)
    min_closed_seconds: float = Field(ge=0.2, le=10)
    min_open_seconds: float = Field(ge=0, le=2)
    no_face_grace_seconds: float = Field(ge=0, le=10)
    perclos: PerclosConfig


class AlertConfig(_Section):
    enabled: bool
    sound: bool


class LoggingConfig(_Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class AppConfig(_Section):
    server: ServerConfig
    camera: CameraConfig
    detection: DetectionConfig
    alerts: AlertConfig
    logging: LoggingConfig


def _format_validation_error(path: Path, error: ValidationError) -> str:
    lines = [f"Invalid configuration in {path}:"]
    for item in error.errors():
        field = ".".join(str(part) for part in item["loc"])
        message = item["msg"]
        if item["type"] not in ("missing", "extra_forbidden"):
            message += f" (got {item['input']!r})"
        lines.append(f"  - {field}: {message}")
    return "\n".join(lines)


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}") from None
    except OSError as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc}") from None

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from None

    if not isinstance(data, dict):
        raise ConfigError(f"Invalid configuration in {path}: top level must be a mapping")

    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(path, exc)) from None


def resolve_config_path(environ: Mapping[str, str] = os.environ) -> Path:
    """Config path from the APP_CONFIG environment variable, else the repo default."""
    return Path(environ.get(CONFIG_ENV_VAR) or DEFAULT_CONFIG_PATH)


def main(argv: list[str] | None = None) -> int:
    """`python -m app.config --check FILE` validates a config (used by the Docker build)."""
    parser = argparse.ArgumentParser(description="Validate a configuration file.")
    parser.add_argument("--check", metavar="FILE", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.check)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(
        f"Config OK: {args.check} "
        f"(ear_threshold={config.detection.ear_threshold}, "
        f"min_closed_seconds={config.detection.min_closed_seconds}, "
        f"port={config.server.port})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

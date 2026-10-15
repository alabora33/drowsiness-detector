import os
import tempfile
from pathlib import Path
from threading import RLock

import yaml

from app.config import AppConfig

EDIT_FIELDS = {
    "ear_threshold",
    "min_closed_seconds",
    "min_open_seconds",
    "no_face_grace_seconds",
    "low_light_threshold",
}
EDIT_PERCLOS = {
    "enabled",
    "window_seconds",
    "threshold",
}


class ConfigManager:
    def __init__(
        self,
        config: AppConfig,
        settings_path: str | Path | None = None,
    ):
        self._base_config = config
        self._config = config
        self._version = 0
        self._lock = RLock()
        self._settings_path = Path(settings_path) if settings_path is not None else None
        if self._settings_path and self._settings_path.exists():
            with self._settings_path.open(encoding="utf-8") as file:
                saved = yaml.safe_load(file)

            if not isinstance(saved, dict):
                raise ValueError("Kaydedilmiş ayarlar geçersiz")

            self._config = self._merge(config, saved)

    def get_config(self) -> AppConfig:
        with self._lock:
            return self._config

    def get_snapshot(self) -> tuple[AppConfig, int]:
        with self._lock:
            return self._config, self._version

    def _merge(self, config: AppConfig, changes: dict) -> AppConfig:

        a = set(changes) - EDIT_FIELDS - {"perclos"}

        if a:
            raise ValueError(f"Değiştirilemeyen alanlar: {sorted(a)}")

        data = config.model_dump()

        for key in EDIT_FIELDS:
            if key in changes:
                data["detection"][key] = changes[key]

        if "perclos" in changes:
            perclos = changes["perclos"]

            if not isinstance(perclos, dict):
                raise ValueError("perclos bir nesne")

            unknown_perclos = set(perclos) - EDIT_PERCLOS

            if unknown_perclos:
                raise ValueError(f"Değiştirilemeyen PERCLOS alanları: {sorted(unknown_perclos)}")

            data["detection"]["perclos"].update(perclos)

        return AppConfig.model_validate(data)

    def _save(self, config: AppConfig) -> None:

        if self._settings_path is None:
            return

        detection = config.detection.model_dump()

        saved = {key: detection[key] for key in sorted(EDIT_FIELDS)}
        saved["perclos"] = {key: detection["perclos"][key] for key in sorted(EDIT_PERCLOS)}

        path = self._settings_path

        print(f"KAydedilen {path}")
        temp_name = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".settings-",
                suffix=".tmp",
                delete=False,
            ) as file:
                temp_name = file.name
                yaml.safe_dump(
                    saved,
                    file,
                    allow_unicode=True,
                    sort_keys=True,
                )
                file.flush()
                os.fsync(file.fileno())

            os.replace(temp_name, path)

        finally:
            if temp_name is not None and os.path.exists(temp_name):
                os.unlink(temp_name)

    def update_detection(self, changes: dict) -> AppConfig:

        with self._lock:
            new_config = self._merge(self._config, changes)

            if new_config == self._config:
                return self._config

            print(f"Yeni ayarlar kaydediliyor: {self._settings_path}")
            self._save(new_config)

            self._config = new_config
            self._version += 1

            return self._config

    def reset(self) -> AppConfig:

        with self._lock:
            if self._config == self._base_config:
                return self._config

            self._save(self._base_config)

            self._config = self._base_config
            self._version += 1

            return self._config

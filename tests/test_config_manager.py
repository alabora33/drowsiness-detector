from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import load_config
from app.config_manager import ConfigManager


def test_initial_config_snapshot():
    config_path = Path(__file__).resolve().parents[1] / "configs" / "default.yaml"

    config = load_config(config_path)
    manager = ConfigManager(config)

    current_config, version = manager.get_snapshot()

    assert current_config is config
    assert manager.get_config() is config
    assert version == 0


def test_update_detection_settings():
    config = load_config("configs/default.yaml")
    manager = ConfigManager(config)

    updated = manager.update_detection(
        {
            "ear_threshold": 0.22,
            "min_closed_seconds": 1.0,
        }
    )

    assert updated.detection.ear_threshold == 0.22
    assert updated.detection.min_closed_seconds == 1.0
    assert manager.get_snapshot()[1] == 1

    assert config.detection.ear_threshold == 0.18


def test_invalid_settings_config():
    config = load_config("configs/default.yaml")
    manager = ConfigManager(config)

    with pytest.raises(ValidationError):
        manager.update_detection(
            {
                "ear_threshold": 0.90,
            }
        )

    current, version = manager.get_snapshot()

    assert current == config
    assert version == 0


def test_non_editable_settings_rejected():
    config = load_config("configs/default.yaml")
    manager = ConfigManager(config)

    with pytest.raises(ValueError):
        manager.update_detection(
            {
                "model_path": "new-model.task",
            }
        )

    assert manager.get_snapshot()[1] == 0


def test_settings_are_saved_and_reloaded(tmp_path):
    config = load_config("configs/default.yaml")
    settings_file = tmp_path / "settings.yaml"

    manager = ConfigManager(config, settings_file)

    manager.update_detection(
        {
            "ear_threshold": 0.23,
            "min_closed_seconds": 1.1,
            "perclos": {
                "threshold": 0.4,
            },
        }
    )

    assert settings_file.exists()
    assert manager.get_snapshot()[1] == 1

    restarted = ConfigManager(config, settings_file)

    current = restarted.get_config()

    assert current.detection.ear_threshold == 0.23
    assert current.detection.min_closed_seconds == 1.1
    assert current.detection.perclos.threshold == 0.4

    assert config.detection.ear_threshold == 0.18


def test_reset_settings(tmp_path):
    config = load_config("configs/default.yaml")
    settings_file = tmp_path / "settings.yaml"

    manager = ConfigManager(config, settings_file)

    manager.update_detection({"ear_threshold": 0.25})
    manager.reset()

    assert manager.get_config() == config
    assert manager.get_snapshot()[1] == 2

    restarted = ConfigManager(config, settings_file)
    assert restarted.get_config() == config


def test_failed_save_does_not_apply_settings(tmp_path):
    config = load_config("configs/default.yaml")

    settings_file = tmp_path / "missing" / "settings.yaml"
    print(f"settings_file: {settings_file}")
    manager = ConfigManager(config, settings_file)

    with pytest.raises(OSError):
        manager.update_detection({"ear_threshold": 0.25})

    assert manager.get_config() == config
    assert manager.get_snapshot()[1] == 0
    assert not settings_file.exists()


def test_invalid_perclos_change_settings(tmp_path):
    config = load_config("configs/default.yaml")
    manager = ConfigManager(config, tmp_path / "settings.yaml")

    with pytest.raises(ValidationError):
        manager.update_detection(
            {
                "perclos": {
                    "threshold": 1.5,
                }
            }
        )

    assert manager.get_config() == config
    assert manager.get_snapshot()[1] == 0
    assert not (tmp_path / "settings.yaml").exists()

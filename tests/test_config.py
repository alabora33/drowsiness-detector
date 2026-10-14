from pathlib import Path

import pytest
import yaml

from app.config import (
    ConfigError,
    load_config,
    main,
    resolve_config_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = sorted((REPO_ROOT / "configs").glob("*.yaml"))


def write_config(tmp_path: Path, **overrides) -> Path:
    """Write the default config with dotted-key overrides, e.g. detection__ear_threshold=0.3."""
    data = yaml.safe_load((REPO_ROOT / "configs/default.yaml").read_text())
    for dotted, value in overrides.items():
        *parents, leaf = dotted.split("__")
        node = data
        for key in parents:
            node = node[key]
        if value is None:
            del node[leaf]
        else:
            node[leaf] = value
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.name)
def test_example_configs_are_valid(path):
    load_config(path)


def test_at_least_two_example_configs():
    assert len(CONFIGS) >= 2


def test_default_config_values():
    config = load_config(REPO_ROOT / "configs/default.yaml")
    assert config.detection.ear_threshold == 0.18
    assert config.detection.min_closed_seconds == 1.5
    assert config.server.port == 8000


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_malformed_yaml(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("server: [unclosed\n")
    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_config(path)


def test_top_level_must_be_mapping(tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(path)


def test_out_of_range_value_names_the_field(tmp_path):
    path = write_config(tmp_path, detection__ear_threshold=2.0)
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "detection.ear_threshold" in str(exc.value)
    assert "2.0" in str(exc.value)


def test_unknown_key_is_rejected(tmp_path):
    path = write_config(tmp_path, detection__ear_treshold=0.2)
    with pytest.raises(ConfigError, match="detection.ear_treshold"):
        load_config(path)


def test_missing_required_field(tmp_path):
    path = write_config(tmp_path, detection__min_closed_seconds=None)
    with pytest.raises(ConfigError, match="detection.min_closed_seconds: Field required"):
        load_config(path)


def test_invalid_log_level(tmp_path):
    path = write_config(tmp_path, logging__level="LOUD")
    with pytest.raises(ConfigError, match="logging.level"):
        load_config(path)


def test_invalid_port_type(tmp_path):
    path = write_config(tmp_path, server__port="http")
    with pytest.raises(ConfigError, match="server.port"):
        load_config(path)


def test_config_is_immutable():
    config = load_config(REPO_ROOT / "configs/default.yaml")
    with pytest.raises(ValueError):
        config.detection.ear_threshold = 0.5


def test_resolve_config_path_prefers_env():
    assert resolve_config_path({"APP_CONFIG": "/config/x.yaml"}) == Path("/config/x.yaml")
    assert resolve_config_path({}) == Path("configs/default.yaml")


def test_check_cli(capsys):
    assert main(["--check", str(REPO_ROOT / "configs/default.yaml")]) == 0
    assert "Config OK" in capsys.readouterr().out
    assert main(["--check", str(REPO_ROOT / "tests/fixtures/invalid_config.yaml")]) == 1
    err = capsys.readouterr().err
    assert "detection.ear_threshold" in err
    assert "logging.level" in err

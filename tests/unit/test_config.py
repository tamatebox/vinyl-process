"""Configuration: resolution order, strictness, and digest stability."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from vinyl_process.config import (
    CONFIG_ENV_VAR,
    EXAMPLE_CONFIG,
    Config,
    default_config,
    find_config,
    load_config,
)
from vinyl_process.errors import ConfigError


def write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_defaults_need_no_file() -> None:
    config = default_config()
    assert config.source_path is None
    assert config.preferences.export_format == "flac"
    assert config.analyzer_params("rms_profile") == {}


def test_example_config_is_valid_and_covers_both_halves() -> None:
    raw = tomllib.loads(EXAMPLE_CONFIG)
    config = Config.model_validate(raw)
    assert config.preferences.declick_intent == "balanced"
    clicks = config.analyzer_params("clicks")
    # The ladder is a measurement grid; which rung to run at is a decision and
    # lives in the plan, so the config must not look like it settles that.
    assert clicks["threshold_ladder"][0] < clicks["threshold_ratio"]
    assert clicks["threshold_ratio"] < clicks["threshold_ladder"][-1]


def test_explicit_path_wins_over_environment_and_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = write(tmp_path / "explicit.toml", '[preferences]\nexport_format = "wav"\n')
    env = write(tmp_path / "env.toml", '[preferences]\nexport_format = "aiff"\n')
    monkeypatch.setenv(CONFIG_ENV_VAR, str(env))
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "vinyl-process.toml", '[preferences]\nexport_format = "flac"\n')

    assert load_config(explicit).preferences.export_format == "wav"
    assert load_config().preferences.export_format == "aiff"
    monkeypatch.delenv(CONFIG_ENV_VAR)
    assert load_config().preferences.export_format == "flac"


def test_project_config_is_found_from_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    path = write(tmp_path / "vinyl-process.toml", "[analyzer.clicks]\nthreshold_mad = 4.5\n")
    assert find_config() == path
    assert load_config().analyzer_params("clicks") == {"threshold_mad": 4.5}


def test_a_missing_explicit_path_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.toml")


def test_malformed_toml_is_reported_with_its_path(tmp_path: Path) -> None:
    path = write(tmp_path / "bad.toml", "this is not toml")
    with pytest.raises(ConfigError, match=r"bad\.toml"):
        load_config(path)


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    path = write(tmp_path / "typo.toml", '[preferences]\nexport_formta = "flac"\n')
    with pytest.raises(ConfigError, match="invalid configuration"):
        load_config(path)


def test_out_of_range_preference_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path / "loud.toml", "[preferences]\nnormalize_target_db = 3.0\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_digest_covers_analyzer_settings_only() -> None:
    """Preferences steer *skills*, so they must not change a measurement digest."""
    base = default_config()
    tuned = Config(analyzer={"clicks": {"threshold_mad": 4.5}})
    with_preference = Config(preferences={"declick_intent": "aggressive"})  # type: ignore[arg-type]

    assert base.digest() == with_preference.digest()
    assert base.digest() != tuned.digest()
    assert tuned.digest() == Config(analyzer={"clicks": {"threshold_mad": 4.5}}).digest()

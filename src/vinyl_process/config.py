"""Configuration.

Two clearly separated halves, because they cross different layer boundaries:

``[analyzer.*]``
    Measurement parameters (window sizes, detection thresholds). They change
    what the Analyzer *measures*, so the effective values are recorded in
    ``analysis.json`` — both per section (``meta.params``) and as a whole
    (``config_digest``), which keeps a document explainable years later.

``[preferences]``
    The user's taste: export format, target level, how conservative declicking
    should be. **Only planning skills read these.** They influence the plan, and
    the plan alone drives the executor, so the plan stays the single complete
    record of what was done. Nothing in :mod:`vinyl_process.executor` may consult
    preferences.

Resolution order (first match wins): explicit path -> ``$VINYL_PROCESS_CONFIG``
-> ``./vinyl-process.toml`` -> ``$XDG_CONFIG_HOME/vinyl-process/config.toml``
-> built-in defaults.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError

from vinyl_process.errors import ConfigError
from vinyl_process.hashing import digest_json
from vinyl_process.models.common import ContractModel

CONFIG_ENV_VAR = "VINYL_PROCESS_CONFIG"
PROJECT_CONFIG_NAME = "vinyl-process.toml"
DeclickIntent = Literal["conservative", "balanced", "aggressive"]
TitleStyle = Literal["as_printed", "transliterate"]


class Preferences(ContractModel):
    """User taste, consumed by planning skills only."""

    export_format: Literal["flac", "wav", "aiff"] = "flac"
    export_bit_depth: Literal[16, 24] = 24
    export_sample_rate: int | None = None
    dither: Literal["none", "tpdf"] = "none"
    track_filename_template: str = "{index:02d} - {title}"

    normalize_mode: Literal["album_peak", "album_rms", "track_peak", "none"] = "album_peak"
    normalize_target_db: float = Field(default=-1.0, le=0.0)

    declick_intent: DeclickIntent = "balanced"
    preferred_declick_engine: str = "native"

    prefer_original_release_year: bool = True
    title_style: TitleStyle = "as_printed"


class Config(ContractModel):
    analyzer: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Per-analyzer parameter overrides, e.g. ``{"rms_profile": {"hop_seconds": 0.05}}``."""

    preferences: Preferences = Field(default_factory=Preferences)
    source_path: str | None = None
    """Where this configuration came from; ``None`` means built-in defaults."""

    def analyzer_params(self, name: str) -> dict[str, Any]:
        return dict(self.analyzer.get(name, {}))

    def digest(self) -> str:
        """Digest of everything that can change a measurement."""
        return digest_json({"analyzer": self.analyzer})


def default_config() -> Config:
    return Config()


def find_config(explicit: str | Path | None = None) -> Path | None:
    """First existing configuration file in resolution order, or ``None``."""
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    env_value = os.environ.get(CONFIG_ENV_VAR)
    if env_value:
        candidates.append(Path(env_value))
    candidates.append(Path.cwd() / PROJECT_CONFIG_NAME)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    candidates.append(base / "vinyl-process" / "config.toml")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    if explicit is not None:
        raise ConfigError(f"configuration file not found: {explicit}")
    return None


def load_config(explicit: str | Path | None = None) -> Config:
    """Load configuration, falling back to built-in defaults."""
    path = find_config(explicit)
    if path is None:
        return default_config()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read configuration {path}: {exc}") from exc
    try:
        config = Config.model_validate({**raw, "source_path": str(path)})
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration {path}:\n{exc}") from exc
    return config


EXAMPLE_CONFIG = """\
# vinyl-process configuration.
#
# [analyzer.*] changes what is measured; the effective values are recorded in
# analysis.json. [preferences] is read by planning skills only — never by the
# executor, so processing_plan.json stays the complete record of a run.

[analyzer.rms_profile]
window_seconds = 0.2
hop_seconds = 0.1

[analyzer.silence]
margin_db = 8.0
min_duration_seconds = 0.5

[analyzer.clicks]
# The detector compares the energy of a click-width window with the energy of its
# neighbourhood, which makes it independent both of how loud the passage is and of
# how much audio it was handed — the latter is why the analyzer, which sees a side,
# and the engine, which sees one track, describe the same events.
# The ladder reported as clicks.threshold_sweep. Which rung to *run* at is a
# decision and lives in processing_plan.json, chosen per pressing: no single
# value suits a collection spanning near-mint to heavily worn.
threshold_ladder = [10.0, 20.0, 35.0, 50.0, 75.0, 100.0, 150.0, 250.0, 400.0]
# Which rung is promoted to the top-level count and rates. A reporting choice.
threshold_ratio = 50.0
max_width_ms = 2.0

[preferences]
export_format = "flac"
export_bit_depth = 24
normalize_mode = "album_peak"
normalize_target_db = -1.0
declick_intent = "balanced"
track_filename_template = "{index:02d} - {title}"
"""

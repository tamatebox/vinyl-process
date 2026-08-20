"""Shared fixtures.

The synthesised recording and its analysis are session-scoped: measuring a
20-second stereo file is the slowest thing in the suite and nothing mutates it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.fixtures.synth import SyntheticRecording, write_recording
from vinyl_process.analyzer import run_analysis
from vinyl_process.config import CONFIG_ENV_VAR
from vinyl_process.hashing import digest_bytes
from vinyl_process.models.analysis import AnalysisDocument
from vinyl_process.models.plan import ProcessingPlan


@pytest.fixture(autouse=True)
def _isolated_user_config(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Keep the suite out of the developer's own configuration.

    Resolution ends at ``$XDG_CONFIG_HOME/vinyl-process/config.toml``, so without
    this every run reads whatever happens to be in the home directory. That is not
    hypothetical: a real ``[rip]`` section appearing there turned ``find_config``'s
    missing-``--config`` behaviour from "raises" into "silently falls back", and
    the assertion that should have caught the bug had been green only because the
    file did not exist.
    """
    empty = tmp_path_factory.mktemp("xdg-config")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(empty))
    monkeypatch.setenv("HOME", str(empty))
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    yield
    monkeypatch.undo()


@pytest.fixture(scope="session")
def recording(tmp_path_factory: pytest.TempPathFactory) -> SyntheticRecording:
    directory = tmp_path_factory.mktemp("recording")
    return write_recording(directory / "side-a.wav")


@pytest.fixture(scope="session")
def analysis(recording: SyntheticRecording) -> AnalysisDocument:
    return run_analysis(recording.path)


@pytest.fixture
def plan(recording: SyntheticRecording, analysis: AnalysisDocument) -> ProcessingPlan:
    """A plan a competent plan-album run would have produced for the fixture."""
    return build_plan(recording, analysis)


def build_plan(
    recording: SyntheticRecording, analysis: AnalysisDocument, **overrides: object
) -> ProcessingPlan:
    def samples(seconds: float) -> int:
        return round(seconds * recording.sample_rate)

    payload: dict[str, object] = {
        "created_by": "test fixture",
        "source": analysis.source.model_dump(),
        "analysis": {
            "path": "analysis.json",
            "sha256": digest_bytes((analysis.model_dump_json(indent=2) + "\n").encode("utf-8")),
        },
        "split": {
            "engine": "native",
            "tracks": [
                {
                    "index": index + 1,
                    "start_sample": samples(start),
                    "end_sample": samples(end + 0.1),
                    "fade_in_ms": 20.0,
                    "fade_out_ms": 30.0,
                }
                for index, (start, end) in enumerate(recording.programme)
            ],
        },
        "declick": {"engine": "native", "algorithm": "block_ratio", "threshold": 20.0},
        "normalize": {"engine": "native", "mode": "album_peak", "target_db": -1.0},
        "metadata": {
            "album": "Test Pressing",
            "album_artist": "Synthetic Ensemble",
            "year": 1973,
            "tracks": [
                {"index": index + 1, "title": f"Movement {index + 1}", "position": f"A{index + 1}"}
                for index in range(len(recording.programme))
            ],
        },
        "export": {"format": "flac", "bit_depth": 24},
    }
    payload.update(overrides)
    return ProcessingPlan.model_validate(payload)


@pytest.fixture
def plan_file(plan: ProcessingPlan, tmp_path: Path) -> Path:
    path = tmp_path / "processing_plan.json"
    path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path

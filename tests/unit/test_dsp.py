"""DSP engines: exact arithmetic, honest capabilities, no hidden decisions."""

from __future__ import annotations

import shutil

import numpy as np
import pytest

from vinyl_process.audio import AudioBuffer
from vinyl_process.dsp import Capability, DspEngine, get_engine, list_engines, register_engine
from vinyl_process.dsp.engines.native import NativeEngine
from vinyl_process.errors import (
    EngineNotFoundError,
    EngineUnavailableError,
    ExecutionError,
    UnsupportedOperationError,
)
from vinyl_process.models.plan import DeclickPlan, TrackBoundary
from vinyl_process.signal_ops import amplitude_to_db

SAMPLE_RATE = 44100
HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def tone(seconds: float = 1.0, amplitude: float = 0.4) -> AudioBuffer:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    signal = amplitude * np.sin(2 * np.pi * 440 * t)
    return AudioBuffer(np.column_stack([signal, signal]), SAMPLE_RATE)


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #
def test_builtin_engines_are_registered() -> None:
    names = {engine.name for engine in list_engines()}
    assert {"native", "ffmpeg"} <= names


def test_unknown_engine_names_the_alternatives() -> None:
    with pytest.raises(EngineNotFoundError, match="available: ffmpeg, native"):
        get_engine("nope")


def test_registering_a_replacement_engine() -> None:
    class Stub(DspEngine):
        name = "test-stub"

        def capabilities(self) -> frozenset:
            return frozenset({"gain"})

        def version(self) -> str:
            return "stub 1"

    register_engine(Stub())
    assert get_engine("test-stub").version() == "stub 1"
    with pytest.raises(EngineNotFoundError, match="already registered"):
        register_engine(Stub())
    register_engine(Stub(), replace=True)


def test_unavailable_engine_is_refused_before_touching_audio() -> None:
    class Missing(DspEngine):
        name = "test-missing"

        def capabilities(self) -> frozenset:
            return frozenset({"gain"})

        def version(self) -> str:
            return "missing"

        def is_available(self) -> bool:
            return False

    register_engine(Missing(), replace=True)
    with pytest.raises(EngineUnavailableError):
        get_engine("test-missing").require("gain")


def test_capability_gaps_are_reported_not_silently_ignored() -> None:
    engine = get_engine("ffmpeg")
    with pytest.raises(UnsupportedOperationError, match="does not support split"):
        engine.require("split")
    with pytest.raises(UnsupportedOperationError):
        engine.split(tone(), [])


def test_describe_reports_status_and_capabilities() -> None:
    described = get_engine("native").describe()
    assert "native" in described
    assert "split" in described


# --------------------------------------------------------------------------- #
# native engine
# --------------------------------------------------------------------------- #
def test_split_is_sample_exact() -> None:
    engine = NativeEngine()
    audio = tone(2.0)
    tracks = [
        TrackBoundary(index=1, start_sample=0, end_sample=SAMPLE_RATE),
        TrackBoundary(index=2, start_sample=SAMPLE_RATE, end_sample=2 * SAMPLE_RATE),
    ]
    first, second = engine.split(audio, tracks)
    assert first.num_frames == SAMPLE_RATE
    assert np.array_equal(first.samples, audio.samples[:SAMPLE_RATE])
    assert np.array_equal(second.samples, audio.samples[SAMPLE_RATE:])


def test_split_applies_only_the_fades_the_plan_asks_for() -> None:
    engine = NativeEngine()
    audio = AudioBuffer(np.ones((SAMPLE_RATE, 2)), SAMPLE_RATE)
    faded, plain = engine.split(
        audio,
        [
            TrackBoundary(
                index=1, start_sample=0, end_sample=1000, fade_in_ms=5.0, fade_out_ms=5.0
            ),
            TrackBoundary(index=2, start_sample=1000, end_sample=2000),
        ],
    )
    assert faded.samples[0, 0] == pytest.approx(0.0)
    assert faded.samples[-1, 0] == pytest.approx(0.0, abs=1e-9)
    assert np.array_equal(plain.samples, np.ones((1000, 2)))


def test_split_clamps_to_the_end_of_the_source_but_rejects_starting_past_it() -> None:
    engine = NativeEngine()
    audio = tone(1.0)
    (piece,) = engine.split(
        audio, [TrackBoundary(index=1, start_sample=0, end_sample=SAMPLE_RATE * 2)]
    )
    assert piece.num_frames == SAMPLE_RATE
    with pytest.raises(ExecutionError, match="beyond the end"):
        engine.split(
            audio,
            [TrackBoundary(index=1, start_sample=SAMPLE_RATE, end_sample=SAMPLE_RATE + 10)],
        )


@pytest.mark.parametrize("gain_db", [-12.0, -6.0206, 0.0, 3.0])
def test_gain_is_exact(gain_db: float) -> None:
    audio = tone()
    result = NativeEngine().apply_gain(audio, gain_db)
    expected = 10.0 ** (gain_db / 20.0)
    assert np.allclose(result.samples, audio.samples * expected)
    assert float(amplitude_to_db(np.max(np.abs(result.samples)))) == pytest.approx(
        float(amplitude_to_db(np.max(np.abs(audio.samples)))) + gain_db, abs=1e-9
    )


def test_declick_repairs_and_is_deterministic() -> None:
    engine = NativeEngine()
    audio = tone(1.0)
    damaged = audio.samples.copy()
    damaged[20_000:20_003] += 0.5
    buffer = AudioBuffer(damaged, SAMPLE_RATE)

    repaired = engine.declick(buffer, DeclickPlan())
    window = slice(19_950, 20_060)
    assert np.max(np.abs(repaired.samples[window] - audio.samples[window])) < np.max(
        np.abs(damaged[window] - audio.samples[window])
    )
    again = engine.declick(buffer, DeclickPlan())
    assert np.array_equal(repaired.samples, again.samples)


def test_declick_passes_plan_parameters_through_to_the_detector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``params`` is the documented escape hatch for engine-specific knobs."""
    from vinyl_process.dsp.engines import native as native_module

    seen: dict[str, object] = {}

    def spy(mono, sample_rate, threshold_mad, max_width_ms, highpass_hz=3000.0):
        seen.update(threshold_mad=threshold_mad, max_width_ms=max_width_ms, highpass_hz=highpass_hz)
        return []

    monkeypatch.setattr(native_module, "click_events", spy)
    NativeEngine().declick(
        tone(),
        DeclickPlan(threshold=4.5, max_click_width_ms=1.5, params={"highpass_hz": 8000.0}),
    )
    assert seen == {"threshold_mad": 4.5, "max_width_ms": 1.5, "highpass_hz": 8000.0}


def test_unknown_declick_algorithm_is_rejected() -> None:
    with pytest.raises(ExecutionError, match="does not implement algorithm"):
        NativeEngine().declick(tone(), DeclickPlan(algorithm="magic"))


# --------------------------------------------------------------------------- #
# ffmpeg engine
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg is not installed")
def test_ffmpeg_gain_agrees_with_the_native_engine() -> None:
    audio = tone()
    native = NativeEngine().apply_gain(audio, -6.0)
    external = get_engine("ffmpeg").apply_gain(audio, -6.0)
    assert external.num_frames == native.num_frames
    # Interchangeable engines must agree numerically; ffmpeg's volume filter only
    # does so when asked for double precision, which the engine sets explicitly.
    assert np.max(np.abs(external.samples - native.samples)) < 1e-12


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg is not installed")
def test_ffmpeg_declick_runs_and_reports_its_version() -> None:
    engine = get_engine("ffmpeg")
    audio = tone(1.0)
    damaged = audio.samples.copy()
    damaged[20_000:20_003] += 0.5
    result = engine.declick(
        AudioBuffer(damaged, SAMPLE_RATE), DeclickPlan(engine="ffmpeg", algorithm="adeclick")
    )
    assert result.num_frames == audio.num_frames
    assert "ffmpeg" in engine.version()


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg is not installed")
def test_ffmpeg_refuses_a_plan_decision_it_cannot_honour() -> None:
    """Silently dropping ``strength`` would break the plan's completeness."""
    with pytest.raises(ExecutionError, match="strength"):
        get_engine("ffmpeg").declick(
            tone(), DeclickPlan(engine="ffmpeg", algorithm="adeclick", strength=0.5)
        )


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg is not installed")
def test_ffmpeg_rejects_a_native_algorithm_name() -> None:
    with pytest.raises(ExecutionError, match="does not implement algorithm"):
        get_engine("ffmpeg").declick(tone(), DeclickPlan(algorithm="mad_interpolate"))


# --------------------------------------------------------------------------- #
# plug-in discovery
# --------------------------------------------------------------------------- #
class _Plugin(DspEngine):
    name = "test-plugin"

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({"gain"})

    def version(self) -> str:
        return "plugin 1.0"


def fake_entry_points(entries: list[object]):
    """Stand in for ``importlib.metadata.entry_points``, checking the group name."""

    def _entry_points(group: str) -> list[object]:
        assert group == "vinyl_process.dsp_engines"
        return entries

    return _entry_points


@pytest.fixture
def fresh_registry(monkeypatch: pytest.MonkeyPatch):
    """A registry that reloads, so entry-point discovery can be observed."""
    from vinyl_process.dsp import registry as registry_module

    monkeypatch.setattr(registry_module, "_ENGINES", {})
    monkeypatch.setattr(registry_module, "_LOADED", False)
    return registry_module


def test_entry_point_engines_are_discovered(
    fresh_registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Entry:
        name = "test-plugin"

        @staticmethod
        def load():
            return _Plugin

    monkeypatch.setattr(fresh_registry, "entry_points", fake_entry_points([Entry()]))
    assert fresh_registry.get_engine("test-plugin").version() == "plugin 1.0"
    assert {engine.name for engine in fresh_registry.list_engines()} >= {"native", "test-plugin"}


def test_a_broken_plugin_does_not_break_the_builtins(
    fresh_registry, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class Exploding:
        name = "test-exploding"

        @staticmethod
        def load():
            raise RuntimeError("bad plug-in")

    class NotAnEngine:
        name = "test-not-an-engine"

        @staticmethod
        def load():
            return lambda: "definitely not an engine"

    monkeypatch.setattr(
        fresh_registry, "entry_points", fake_entry_points([Exploding(), NotAnEngine()])
    )
    with caplog.at_level("ERROR"):
        names = {engine.name for engine in fresh_registry.list_engines()}

    assert names == {"native", "ffmpeg"}
    assert "test-exploding" in caplog.text
    assert "test-not-an-engine" in caplog.text

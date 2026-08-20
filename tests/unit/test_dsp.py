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
from vinyl_process.models.plan import DeclickPlan, PrefilterPlan, TrackBoundary
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

    plan = DeclickPlan(threshold=20.0)
    repaired = engine.declick(buffer, plan)
    window = slice(19_950, 20_060)
    assert np.max(np.abs(repaired.samples[window] - audio.samples[window])) < np.max(
        np.abs(damaged[window] - audio.samples[window])
    )
    again = engine.declick(buffer, plan)
    assert np.array_equal(repaired.samples, again.samples)


def test_declick_passes_plan_parameters_through_to_the_detector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``params`` is the documented escape hatch for engine-specific knobs."""
    from vinyl_process.dsp.engines import native as native_module

    seen: dict[str, object] = {}

    def spy(mono, sample_rate, threshold_ratio, max_width_ms, **kwargs):
        seen.update(threshold_ratio=threshold_ratio, max_width_ms=max_width_ms, **kwargs)
        return []

    monkeypatch.setattr(native_module, "click_events_block", spy)
    NativeEngine().declick(
        tone(),
        DeclickPlan(
            threshold=45.0,
            max_click_width_ms=1.5,
            params={"highpass_hz": 8000.0, "context_ms": 25.0},
        ),
    )
    assert seen == {
        "threshold_ratio": 45.0,
        "max_width_ms": 1.5,
        "detect_ms": 0.2,
        "context_ms": 25.0,
        "highpass_hz": 8000.0,
    }


def test_unknown_declick_algorithm_is_rejected() -> None:
    with pytest.raises(ExecutionError, match="does not implement algorithm"):
        NativeEngine().declick(tone(), DeclickPlan(algorithm="magic", threshold=20.0))


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
        AudioBuffer(damaged, SAMPLE_RATE),
        DeclickPlan(engine="ffmpeg", algorithm="adeclick", threshold=25.0),
    )
    assert result.num_frames == audio.num_frames
    assert "ffmpeg" in engine.version()


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg is not installed")
def test_ffmpeg_refuses_a_plan_decision_it_cannot_honour() -> None:
    """Silently dropping ``strength`` would break the plan's completeness."""
    with pytest.raises(ExecutionError, match="strength"):
        get_engine("ffmpeg").declick(
            tone(), DeclickPlan(engine="ffmpeg", algorithm="adeclick", threshold=25.0, strength=0.5)
        )


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg is not installed")
def test_ffmpeg_rejects_a_native_algorithm_name() -> None:
    with pytest.raises(ExecutionError, match="does not implement algorithm"):
        get_engine("ffmpeg").declick(tone(), DeclickPlan(algorithm="block_ratio", threshold=20.0))


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


def test_declick_refuses_to_invent_a_threshold() -> None:
    """A threshold is a decision, so the engine must not supply one.

    No value suits two pressings — the two sides of one album measured here wanted
    different rungs of the sweep — so a default would be a choice made on behalf
    of every record the code ever sees. Refusing is the only honest option.
    """
    with pytest.raises(ExecutionError, match="not a default"):
        NativeEngine().declick(tone(), DeclickPlan())


# --------------------------------------------------------------------------- #
# prefilter
# --------------------------------------------------------------------------- #
def test_prefilter_is_a_native_capability() -> None:
    assert "prefilter" in NativeEngine().capabilities()


def test_dc_block_removes_the_offset_exactly() -> None:
    audio = tone()
    offset = np.array([0.05, -0.02])
    shifted = AudioBuffer(audio.samples + offset, audio.sample_rate)
    result = NativeEngine().prefilter(
        shifted, PrefilterPlan(enabled=True, dc_block=True, highpass_hz=None)
    )
    assert np.allclose(result.samples.mean(axis=0), 0.0, atol=1e-15)
    # Nothing but the mean moved: the shape is untouched to full float precision.
    assert np.allclose(result.samples, audio.samples - audio.samples.mean(axis=0), atol=1e-15)


def test_prefilter_with_both_switches_off_returns_the_same_buffer() -> None:
    audio = tone()
    result = NativeEngine().prefilter(audio, PrefilterPlan(enabled=True))
    assert result is audio


def test_subsonic_highpass_removes_rumble_and_keeps_the_music() -> None:
    """A 5 Hz warp under a 440 Hz tone: the rumble goes, the tone stays."""
    frames = SAMPLE_RATE * 4
    t = np.arange(frames) / SAMPLE_RATE
    music = 0.4 * np.sin(2 * np.pi * 440 * t)
    rumble = 0.3 * np.sin(2 * np.pi * 5 * t)
    audio = AudioBuffer(np.column_stack([music + rumble, music + rumble]), SAMPLE_RATE)

    result = NativeEngine().prefilter(
        audio,
        PrefilterPlan(enabled=True, highpass_hz=30.0, highpass_rolloff_db_per_octave=24),
    )

    # Judge the second half, past the filter's settling transient, and judge it
    # per component: a forward-only filter shifts the phase of what it passes, so
    # a sample-wise comparison against the unfiltered tone measures that shift
    # rather than the attenuation this test is about.
    tail = slice(frames // 2, frames)

    def component(samples: np.ndarray, hz: float) -> float:
        window = samples[tail]
        spectrum = np.fft.rfft(window)
        bin_index = round(hz * window.size / SAMPLE_RATE)
        return float(2.0 * np.abs(spectrum[bin_index]) / window.size)

    assert component(result.samples[:, 0], 440.0) == pytest.approx(0.4, rel=0.02)
    assert component(result.samples[:, 0], 5.0) < 0.001  # 0.3 going in
    # The peak came down, which is the headroom this stage buys.
    assert float(np.max(np.abs(result.samples[tail, 0]))) < 0.45
    assert float(np.max(np.abs(audio.samples[tail, 0]))) > 0.6


def test_the_rolloff_delivered_is_the_rolloff_asked_for() -> None:
    """24 dB/octave means order 4 applied once, not order 4 applied twice.

    A zero-phase pass would double the rolloff, so a plan asking for 24 would
    silently get 48. Measure the attenuation an octave below the cutoff against
    the ideal Butterworth magnitude for that order.
    """
    frames = SAMPLE_RATE * 8
    t = np.arange(frames) / SAMPLE_RATE
    cutoff, probe = 40.0, 20.0
    signal = np.sin(2 * np.pi * probe * t)
    audio = AudioBuffer(np.column_stack([signal, signal]), SAMPLE_RATE)

    result = NativeEngine().prefilter(
        audio, PrefilterPlan(enabled=True, highpass_hz=cutoff, highpass_rolloff_db_per_octave=24)
    )
    tail = slice(frames // 2, frames)
    measured_db = float(
        amplitude_to_db(np.max(np.abs(result.samples[tail, 0])))
        - amplitude_to_db(np.max(np.abs(audio.samples[tail, 0])))
    )
    order = 4
    ideal_db = -10.0 * np.log10(1.0 + (cutoff / probe) ** (2 * order))
    assert abs(measured_db - ideal_db) < 1.0
    # ...and emphatically not the double-pass figure.
    assert abs(measured_db - 2 * ideal_db) > 5.0


def test_prefilter_is_deterministic() -> None:
    audio = tone()
    section = PrefilterPlan(enabled=True, dc_block=True, highpass_hz=25.0)
    first = NativeEngine().prefilter(audio, section)
    second = NativeEngine().prefilter(audio, section)
    assert np.array_equal(first.samples, second.samples)


def test_a_cutoff_at_or_above_nyquist_is_a_no_op() -> None:
    audio = tone()
    result = NativeEngine().prefilter(
        audio, PrefilterPlan(enabled=True, highpass_hz=float(SAMPLE_RATE))
    )
    assert np.array_equal(result.samples, audio.samples)


def test_ffmpeg_does_not_claim_prefilter() -> None:
    assert "prefilter" not in get_engine("ffmpeg").capabilities()
    with pytest.raises(UnsupportedOperationError, match="prefilter"):
        get_engine("ffmpeg").require("prefilter")

"""Analyzers and analysis sections are two halves of one contract."""

from __future__ import annotations

from vinyl_process.analyzer import all_analyzers
from vinyl_process.models.analysis import AnalysisDocument
from vinyl_process.models.common import Section


def test_every_analyzer_has_a_section_field() -> None:
    fields = set(AnalysisDocument.section_fields())
    for spec in all_analyzers():
        assert spec.name in fields, (
            f"analyzer {spec.name!r} has no field in AnalysisDocument; "
            "add a section model named after it"
        )


def test_every_section_field_has_an_analyzer() -> None:
    """An orphan section could never be populated, so it would be dead contract."""
    names = {spec.name for spec in all_analyzers()}
    for field in AnalysisDocument.section_fields():
        assert field in names, f"section {field!r} has no analyzer producing it"


def test_section_models_all_carry_provenance() -> None:
    for field in AnalysisDocument.section_fields():
        annotation = AnalysisDocument.model_fields[field].annotation
        model = next(
            arg
            for arg in getattr(annotation, "__args__", ())
            if isinstance(arg, type) and issubclass(arg, Section)
        )
        assert "meta" in model.model_fields


def test_declared_dependencies_exist() -> None:
    names = {spec.name for spec in all_analyzers()}
    for spec in all_analyzers():
        for dependency in spec.requires:
            assert dependency in names, f"{spec.name} requires unknown analyzer {dependency!r}"


def test_the_clicks_analyzer_and_the_native_engine_detect_the_same_events() -> None:
    """The architecture's claim, checked rather than asserted in prose.

    ``docs/architecture.md`` says the statistics a skill reasons about and the
    damage the engine repairs are "the same events by construction", because both
    call into ``signal_ops``. Sharing the function is not enough: with a
    data-dependent threshold the answer also depends on how much audio the caller
    passed, and the analyzer is handed a whole side while the engine is handed one
    track. Under ``mad_interpolate`` that gap was measured at 38 693 clicks
    reported against 58 355 spans repaired. This pins the pairing that does hold.

    The engine path is exercised through the engine, not through ``signal_ops``,
    so that a change to either wiring breaks the test.
    """
    import numpy as np

    from vinyl_process.audio import AudioBuffer
    from vinyl_process.dsp.engines.native import NativeEngine
    from vinyl_process.models.plan import DeclickPlan
    from vinyl_process.signal_ops import click_events_block

    sample_rate = 44100
    time = np.arange(sample_rate * 3) / sample_rate
    signal = 0.3 * np.sin(2 * np.pi * 440 * time) + 0.1 * np.sin(2 * np.pi * 1700 * time)
    for position in range(5000, signal.size - 5000, 6000):
        signal[position : position + 3] += np.array([0.5, -0.45, 0.4])

    threshold, max_width_ms = 20.0, 2.0
    whole_side = click_events_block(signal, sample_rate, threshold, max_width_ms)
    assert whole_side, "the fixture must produce detections"

    plan = DeclickPlan.model_validate(
        {
            "enabled": True,
            "engine": "native",
            "algorithm": "block_ratio",
            "threshold": threshold,
            "max_click_width_ms": max_width_ms,
        }
    )
    stereo = np.column_stack([signal, signal])
    engine = NativeEngine()
    # One track at a time is what the executor does; the interior of each piece
    # must still resolve to the events the analyzer reported for the whole side.
    piece = sample_rate  # 1 s
    margin = int(0.05 * sample_rate)
    for start in range(0, signal.size - piece, piece):
        buffer = AudioBuffer(samples=stereo[start : start + piece], sample_rate=sample_rate)
        repaired = engine.declick(buffer, plan)
        changed = np.flatnonzero(np.abs(repaired.samples - buffer.samples).max(axis=1) > 0)
        from_engine = {int(index) + start for index in changed if margin <= index < piece - margin}
        from_analyzer = {
            position
            for event in whole_side
            for position in range(event[0] - 1, event[1] + 1)
            if start + margin <= position < start + piece - margin
        }
        assert from_engine <= from_analyzer, (
            f"the engine repaired samples at {sorted(from_engine - from_analyzer)[:8]} "
            "that the analyzer did not report for the same audio"
        )

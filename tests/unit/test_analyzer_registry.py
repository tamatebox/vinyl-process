"""Analyzer registration and dependency resolution."""

from __future__ import annotations

import pytest

from vinyl_process.analyzer import all_analyzers, get_analyzer, resolve_order
from vinyl_process.analyzer.base import AnalyzerContext, AnalyzerSpec
from vinyl_process.errors import AnalysisError
from vinyl_process.models.analysis import AnalysisDocument
from vinyl_process.models.common import Section


def test_every_analyzer_declares_a_version_and_description() -> None:
    for spec in all_analyzers():
        assert spec.version
        assert spec.description


def test_resolve_order_places_dependencies_first() -> None:
    order = [spec.name for spec in resolve_order(["boundaries"])]
    assert order.index("rms_profile") < order.index("silence") < order.index("boundaries")
    assert order.index("surface_noise") < order.index("silence")


def test_resolve_order_defaults_to_everything() -> None:
    assert {spec.name for spec in resolve_order()} == {spec.name for spec in all_analyzers()}


def test_resolve_order_is_stable() -> None:
    assert [spec.name for spec in resolve_order()] == [spec.name for spec in resolve_order()]


def test_unknown_names_are_rejected_early() -> None:
    with pytest.raises(AnalysisError, match="unknown analyzer"):
        resolve_order(["nope"])
    with pytest.raises(AnalysisError, match="unknown analyzer"):
        get_analyzer("nope")


def test_dependency_cycles_are_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    from vinyl_process.analyzer import registry as registry_module

    all_analyzers()

    def make(name: str, requires: tuple[str, ...]) -> AnalyzerSpec:
        return AnalyzerSpec(
            name=name,
            version="1.0",
            description="cycle",
            requires=requires,
            defaults={},
            fn=lambda _context: Section(),
        )

    monkeypatch.setitem(registry_module._ANALYZERS, "cycle_a", make("cycle_a", ("cycle_b",)))
    monkeypatch.setitem(registry_module._ANALYZERS, "cycle_b", make("cycle_b", ("cycle_a",)))
    with pytest.raises(AnalysisError, match="dependency cycle"):
        resolve_order(["cycle_a"])


def test_merge_params_rejects_typos() -> None:
    spec = get_analyzer("rms_profile")
    assert spec.merge_params({"hop_seconds": 0.5})["hop_seconds"] == 0.5
    with pytest.raises(AnalysisError, match="has no parameter"):
        spec.merge_params({"hop_second": 0.5})


def test_context_requires_report_missing_sections() -> None:
    context = AnalyzerContext(
        audio=None,  # type: ignore[arg-type]
        source=None,  # type: ignore[arg-type]
        format=None,  # type: ignore[arg-type]
        params={"a": "not-a-number"},
        sections={},
    )
    with pytest.raises(AnalysisError, match="not available"):
        context.section("rms_profile")
    with pytest.raises(AnalysisError, match="must be a number"):
        context.number("a")
    with pytest.raises(AnalysisError, match="must be a number"):
        context.number("missing")


def test_typed_section_checks_the_model() -> None:
    from vinyl_process.models.analysis import PeaksSection, RmsProfileSection

    section = RmsProfileSection(window_seconds=0.2, hop_seconds=0.1, values_db=[])
    context = AnalyzerContext(
        audio=None,  # type: ignore[arg-type]
        source=None,  # type: ignore[arg-type]
        format=None,  # type: ignore[arg-type]
        params={},
        sections={"rms_profile": section},
    )
    assert context.typed_section("rms_profile", RmsProfileSection) is section
    with pytest.raises(AnalysisError, match="expected PeaksSection"):
        context.typed_section("rms_profile", PeaksSection)


def test_analyzer_names_match_document_fields() -> None:
    """The runner assembles the document by keyword, so this must hold."""
    assert {spec.name for spec in all_analyzers()} <= set(AnalysisDocument.section_fields())

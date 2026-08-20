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

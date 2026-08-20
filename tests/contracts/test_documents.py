"""The data contracts themselves: round-trips, strictness, and validators."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from vinyl_process.errors import ContractError
from vinyl_process.models import DOCUMENT_MODELS, VersionedDocument, check_major_version
from vinyl_process.models.analysis import AnalysisDocument
from vinyl_process.models.common import SCHEMA_VERSION, Section, SectionMeta
from vinyl_process.models.manifest import ExecutionManifest
from vinyl_process.models.plan import ProcessingPlan

SOURCE: dict[str, Any] = {
    "path": "side-a.wav",
    "sha256": "a" * 64,
    "sample_rate": 44100,
    "channels": 2,
    "num_samples": 441000,
    "duration_seconds": 10.0,
}

MINIMAL_PLAN: dict[str, Any] = {
    "source": SOURCE,
    "split": {"tracks": [{"index": 1, "start_sample": 0, "end_sample": 441000}]},
    "declick": {},
    "normalize": {},
    "metadata": {},
    "export": {},
}


def test_document_types_are_registered_and_self_describing() -> None:
    assert set(DOCUMENT_MODELS) == {"analysis", "processing_plan", "manifest"}
    for name, model in DOCUMENT_MODELS.items():
        assert model.model_fields["document_type"].default == name


@pytest.mark.parametrize("name", sorted(DOCUMENT_MODELS))
def test_documents_default_to_the_current_schema_version(name: str) -> None:
    assert DOCUMENT_MODELS[name].model_fields["schema_version"].default == SCHEMA_VERSION


def test_plan_round_trips_through_json(plan: ProcessingPlan) -> None:
    payload = plan.model_dump_json()
    assert ProcessingPlan.model_validate_json(payload) == plan
    assert json.loads(payload)["document_type"] == "processing_plan"


def test_analysis_round_trips_through_json(analysis: AnalysisDocument) -> None:
    assert AnalysisDocument.model_validate_json(analysis.model_dump_json()) == analysis


@pytest.mark.parametrize("name", sorted(DOCUMENT_MODELS))
def test_unknown_fields_are_rejected(name: str, plan: ProcessingPlan) -> None:
    """A typo in a hand-authored plan must fail loudly, not be ignored."""
    payloads = {
        "processing_plan": MINIMAL_PLAN,
        "analysis": {"generated_by": "t", "source": SOURCE},
        "manifest": {
            "generated_by": "t",
            "run_key": "k",
            "source": SOURCE,
            "plan": {"path": "p", "sha256": "b" * 64},
            "started_at": "now",
            "completed_at": "now",
        },
    }
    model = DOCUMENT_MODELS[name]
    model.model_validate(payloads[name])
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate({**payloads[name], "unexpected": 1})


def test_nested_sections_are_strict_too() -> None:
    with pytest.raises(ValidationError):
        ProcessingPlan.model_validate(
            {**MINIMAL_PLAN, "declick": {"threshhold": 6.0}},
        )


def test_major_version_gate() -> None:
    class Doc(VersionedDocument):
        pass

    check_major_version(Doc(schema_version="1.999"))
    with pytest.raises(ContractError, match="unsupported schema major version"):
        check_major_version(Doc(schema_version="2.0"))


def test_split_requires_contiguous_non_overlapping_tracks() -> None:
    def plan_with(tracks: list[dict[str, int]]) -> None:
        ProcessingPlan.model_validate({**MINIMAL_PLAN, "split": {"tracks": tracks}})

    with pytest.raises(ValidationError, match="at least one track"):
        plan_with([])
    with pytest.raises(ValidationError, match="contiguous"):
        plan_with(
            [
                {"index": 1, "start_sample": 0, "end_sample": 100},
                {"index": 3, "start_sample": 200, "end_sample": 300},
            ]
        )
    with pytest.raises(ValidationError, match="contiguous"):
        plan_with(
            [
                {"index": 2, "start_sample": 0, "end_sample": 100},
                {"index": 1, "start_sample": 200, "end_sample": 300},
            ]
        )
    with pytest.raises(ValidationError, match="overlap"):
        plan_with(
            [
                {"index": 1, "start_sample": 0, "end_sample": 200},
                {"index": 2, "start_sample": 100, "end_sample": 300},
            ]
        )
    with pytest.raises(ValidationError, match="must exceed start_sample"):
        plan_with([{"index": 1, "start_sample": 100, "end_sample": 100}])
    # Gaps between tracks are normal on vinyl and must stay legal.
    plan_with(
        [
            {"index": 1, "start_sample": 0, "end_sample": 100},
            {"index": 2, "start_sample": 5000, "end_sample": 6000},
        ]
    )


def test_disabled_split_needs_no_tracks() -> None:
    ProcessingPlan.model_validate({**MINIMAL_PLAN, "split": {"enabled": False, "tracks": []}})


def test_normalize_target_must_not_boost_above_full_scale() -> None:
    with pytest.raises(ValidationError):
        ProcessingPlan.model_validate({**MINIMAL_PLAN, "normalize": {"target_db": 0.5}})


def test_metadata_track_indices_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="duplicate indices"):
        ProcessingPlan.model_validate(
            {
                **MINIMAL_PLAN,
                "metadata": {"tracks": [{"index": 1, "title": "a"}, {"index": 1, "title": "b"}]},
            }
        )


def test_export_bit_depth_and_format_are_closed_sets() -> None:
    with pytest.raises(ValidationError):
        ProcessingPlan.model_validate({**MINIMAL_PLAN, "export": {"bit_depth": 32}})
    with pytest.raises(ValidationError):
        ProcessingPlan.model_validate({**MINIMAL_PLAN, "export": {"format": "mp3"}})


def test_confidence_is_bounded() -> None:
    Section(meta=SectionMeta(confidence=1.0))
    with pytest.raises(ValidationError):
        Section(meta=SectionMeta(confidence=1.5))
    with pytest.raises(ValidationError):
        Section(meta=SectionMeta(confidence=-0.1))


def test_stage_decisions_are_optional_but_preserved(plan: ProcessingPlan) -> None:
    decided = ProcessingPlan.model_validate(
        {
            **MINIMAL_PLAN,
            "split": {
                **MINIMAL_PLAN["split"],
                "decision": {
                    "skill": "plan-split",
                    "rationale": "silence candidate at 11.1 s",
                    "confidence": 0.9,
                    "inputs": ["analysis.json#boundaries"],
                },
            },
        }
    )
    assert decided.split.decision is not None
    assert decided.split.decision.skill == "plan-split"
    assert plan.declick.decision is None


def test_manifest_output_digests_are_keyed_by_filename() -> None:
    manifest = ExecutionManifest.model_validate(
        {
            "generated_by": "t",
            "run_key": "k",
            "source": SOURCE,
            "plan": {"path": "plan.json", "sha256": "b" * 64},
            "started_at": "now",
            "completed_at": "now",
            "outputs": [
                {
                    "track_index": 1,
                    "path": "/tmp/album/01 - A.flac",
                    "sha256": "c" * 64,
                    "bytes": 10,
                    "num_samples": 100,
                    "sample_rate": 44100,
                    "duration_seconds": 1.0,
                    "source_start_sample": 0,
                    "source_end_sample": 100,
                }
            ],
        }
    )
    assert manifest.output_digests() == {"01 - A.flac": "c" * 64}


def test_analysis_sections_are_optional_so_subsets_stay_valid() -> None:
    document = AnalysisDocument.model_validate({"generated_by": "t", "source": SOURCE})
    assert all(getattr(document, name) is None for name in AnalysisDocument.section_fields())


def test_a_second_side_continues_the_album_numbering() -> None:
    """Side B is its own plan but keeps the album's track numbers, so both sides
    can be exported into one directory without colliding."""
    side_b = ProcessingPlan.model_validate(
        {
            **MINIMAL_PLAN,
            "split": {
                "tracks": [
                    {"index": 6, "start_sample": 0, "end_sample": 100},
                    {"index": 7, "start_sample": 100, "end_sample": 200},
                ]
            },
            "metadata": {
                "total_tracks": 10,
                "tracks": [{"index": 6, "title": "Six"}, {"index": 7, "title": "Seven"}],
            },
        }
    )
    assert side_b.track_indices() == [6, 7]
    assert side_b.metadata.total_tracks == 10
    assert side_b.metadata.title_for(7) == "Seven"


def test_total_tracks_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        ProcessingPlan.model_validate({**MINIMAL_PLAN, "metadata": {"total_tracks": 0}})

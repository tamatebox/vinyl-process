"""Plan validation: every finding this project can report has a test."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import soundfile as sf

from tests.conftest import build_plan
from tests.fixtures.synth import SyntheticRecording
from vinyl_process.dsp import register_engine
from vinyl_process.dsp.base import DspEngine
from vinyl_process.errors import PlanValidationError
from vinyl_process.models.analysis import AnalysisDocument
from vinyl_process.models.plan import ProcessingPlan
from vinyl_process.planning import Finding, raise_for_errors, validate_plan


def codes(findings: list[Finding]) -> set[str]:
    return {finding.code for finding in findings}


def mutated(plan: ProcessingPlan, mutate: Callable[[dict[str, Any]], None]) -> ProcessingPlan:
    """Round-trip a plan through validation with a change applied.

    ``model_copy(update=...)`` skips validation, so nested dicts would stay dicts
    and the test would exercise a plan shape that can never come off disk.
    """
    payload = plan.model_dump(mode="json")
    mutate(payload)
    return ProcessingPlan.model_validate(payload)


def test_a_good_plan_reports_nothing(
    plan: ProcessingPlan, recording: SyntheticRecording, analysis: AnalysisDocument
) -> None:
    assert validate_plan(plan, audio_path=recording.path, analysis=analysis) == []


def test_findings_are_ordered_worst_first(plan: ProcessingPlan) -> None:
    broken = plan.model_copy(
        update={
            "split": plan.split.model_copy(update={"engine": "nope"}),
            "export": plan.export.model_copy(update={"dither": "tpdf"}),
        }
    )
    severities = [finding.severity for finding in validate_plan(broken)]
    assert severities == sorted(severities, key=["error", "warning", "info"].index)


def test_unknown_engine_is_fatal(plan: ProcessingPlan) -> None:
    broken = plan.model_copy(update={"split": plan.split.model_copy(update={"engine": "nope"})})
    findings = validate_plan(broken)
    assert "unknown-engine" in codes(findings)
    with pytest.raises(PlanValidationError, match="not executable"):
        raise_for_errors(findings)


def test_engine_without_the_capability_is_fatal(plan: ProcessingPlan) -> None:
    """ffmpeg deliberately does not implement split."""
    broken = plan.model_copy(update={"split": plan.split.model_copy(update={"engine": "ffmpeg"})})
    assert "engine-capability" in codes(validate_plan(broken))


def test_unavailable_engine_is_fatal(plan: ProcessingPlan) -> None:
    class Absent(DspEngine):
        name = "test-absent"

        def capabilities(self) -> frozenset:
            return frozenset({"split", "declick", "gain"})

        def version(self) -> str:
            return "absent"

        def is_available(self) -> bool:
            return False

    register_engine(Absent(), replace=True)
    broken = plan.model_copy(
        update={"split": plan.split.model_copy(update={"engine": "test-absent"})}
    )
    assert "engine-unavailable" in codes(validate_plan(broken))


def test_disabled_stages_are_not_checked_for_engines(plan: ProcessingPlan) -> None:
    disabled = plan.model_copy(
        update={
            "split": plan.split.model_copy(update={"engine": "nope", "enabled": False}),
            "declick": plan.declick.model_copy(update={"engine": "nope", "enabled": False}),
            "normalize": plan.normalize.model_copy(update={"engine": "nope", "mode": "none"}),
        }
    )
    assert "unknown-engine" not in codes(validate_plan(disabled))


def test_a_track_past_the_end_of_the_recording_is_fatal(plan: ProcessingPlan) -> None:
    def push_past_the_end(payload: dict[str, Any]) -> None:
        payload["split"]["tracks"][-1]["end_sample"] = plan.source.num_samples + 1000

    assert "track-past-end" in codes(validate_plan(mutated(plan, push_past_the_end)))


def test_fades_longer_than_the_track_are_fatal(plan: ProcessingPlan) -> None:
    def shorten_with_long_fade(payload: dict[str, Any]) -> None:
        track = payload["split"]["tracks"][0]
        track["end_sample"] = track["start_sample"] + 100
        track["fade_in_ms"] = 500.0

    found = codes(validate_plan(mutated(plan, shorten_with_long_fade)))
    assert "fade-longer-than-track" in found
    assert "short-track" in found


def test_missing_titles_and_orphan_metadata_are_warnings(
    plan: ProcessingPlan, recording: SyntheticRecording, analysis: AnalysisDocument
) -> None:
    def replace_track_tags(payload: dict[str, Any]) -> None:
        payload["metadata"]["tracks"] = [{"index": 9, "title": "Ghost"}]

    found = codes(validate_plan(mutated(plan, replace_track_tags)))
    assert {"missing-title", "orphan-metadata"} <= found


def test_disabled_split_with_several_tracks_warns(plan: ProcessingPlan) -> None:
    broken = plan.model_copy(update={"split": plan.split.model_copy(update={"enabled": False})})
    assert "unsplit-multitrack" in codes(validate_plan(broken))


def test_a_broken_filename_template_is_fatal(plan: ProcessingPlan) -> None:
    broken = plan.model_copy(
        update={"export": plan.export.model_copy(update={"track_filename_template": "{titel}"})}
    )
    assert "filename-template" in codes(validate_plan(broken))


def test_colliding_filenames_are_fatal(plan: ProcessingPlan) -> None:
    broken = plan.model_copy(
        update={"export": plan.export.model_copy(update={"track_filename_template": "same"})}
    )
    assert "filename-collision" in codes(validate_plan(broken))


def test_export_notes_are_informational(plan: ProcessingPlan) -> None:
    noisy = plan.model_copy(
        update={
            "export": plan.export.model_copy(
                update={"dither": "tpdf", "bit_depth": 24, "sample_rate": 48000}
            )
        }
    )
    found = codes(validate_plan(noisy))
    assert {"pointless-dither", "resampling"} <= found
    assert not [finding for finding in validate_plan(noisy) if finding.severity == "error"]


def test_missing_album_title_warns(plan: ProcessingPlan) -> None:
    broken = plan.model_copy(update={"metadata": plan.metadata.model_copy(update={"album": None})})
    assert "no-album-title" in codes(validate_plan(broken))


def test_missing_audio_and_digest_drift_are_fatal(
    plan: ProcessingPlan, tmp_path: Path, recording: SyntheticRecording
) -> None:
    assert "missing-audio" in codes(validate_plan(plan, audio_path=tmp_path / "absent.wav"))

    other = tmp_path / "other.wav"
    samples, sample_rate = sf.read(str(recording.path), always_2d=True)
    sf.write(str(other), samples[: sample_rate // 2], sample_rate, subtype="PCM_24")
    assert "source-mismatch" in codes(validate_plan(plan, audio_path=other))
    assert "source-mismatch" not in codes(validate_plan(plan, audio_path=other, check_digest=False))


def test_an_analysis_of_another_recording_is_fatal(
    plan: ProcessingPlan, analysis: AnalysisDocument
) -> None:
    foreign = analysis.model_copy(
        update={"source": analysis.source.model_copy(update={"sha256": "0" * 64})}
    )
    assert "analysis-mismatch" in codes(validate_plan(plan, analysis=foreign))


def test_analysis_digest_drift_warns(plan: ProcessingPlan, analysis: AnalysisDocument) -> None:
    findings = validate_plan(plan, analysis=analysis, analysis_digest="f" * 64)
    assert "analysis-digest-drift" in codes(findings)


def test_normalizing_a_clipped_source_warns(
    plan: ProcessingPlan, analysis: AnalysisDocument
) -> None:
    assert analysis.clipping is not None
    clipped = analysis.model_copy(
        update={
            "clipping": analysis.clipping.model_copy(
                update={"clipped_region_count": 3, "clipped_sample_count": 30}
            )
        }
    )
    assert "normalize-clipped-source" in codes(validate_plan(plan, analysis=clipped))


def test_a_track_reaching_into_the_run_out_is_informational(
    recording: SyntheticRecording, analysis: AnalysisDocument
) -> None:
    assert analysis.boundaries is not None

    def extend_into_the_runout(payload: dict[str, Any]) -> None:
        payload["split"]["tracks"][-1]["end_sample"] = recording.num_frames

    stretched = mutated(build_plan(recording, analysis), extend_into_the_runout)
    assert "track-into-runout" in codes(validate_plan(stretched, analysis=analysis))


def test_raise_for_errors_passes_clean_findings() -> None:
    raise_for_errors([Finding("warning", "x", "y")])


def test_a_fade_at_a_gapless_join_is_fatal(plan: ProcessingPlan) -> None:
    """Contiguous boundaries mean gapless: a fade there breaks reassembly."""

    def make_contiguous(payload: dict[str, Any]) -> None:
        tracks = payload["split"]["tracks"]
        tracks[1]["start_sample"] = tracks[0]["end_sample"]

    findings = validate_plan(mutated(plan, make_contiguous))
    assert "gapless-fade" in codes(findings)


def test_a_gapless_side_without_fades_is_accepted(plan: ProcessingPlan) -> None:
    def make_gapless(payload: dict[str, Any]) -> None:
        tracks = payload["split"]["tracks"]
        tracks[1]["start_sample"] = tracks[0]["end_sample"]
        for track in tracks:
            track["fade_in_ms"] = 0.0
            track["fade_out_ms"] = 0.0

    findings = validate_plan(mutated(plan, make_gapless))
    assert "gapless-fade" not in codes(findings)
    assert "hard-cut" not in codes(findings), "a deliberate gapless side must not be nagged"


def test_hard_cuts_without_fades_are_flagged_once(plan: ProcessingPlan) -> None:
    def drop_fades(payload: dict[str, Any]) -> None:
        for track in payload["split"]["tracks"]:
            track["fade_in_ms"] = 0.0
            track["fade_out_ms"] = 0.0

    findings = [f for f in validate_plan(mutated(plan, drop_fades)) if f.code == "hard-cut"]
    assert len(findings) == 1
    assert "click" in findings[0].message

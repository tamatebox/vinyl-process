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


def clipped_analysis(analysis: AnalysisDocument) -> AnalysisDocument:
    assert analysis.clipping is not None
    return analysis.model_copy(
        update={
            "clipping": analysis.clipping.model_copy(
                update={"clipped_region_count": 3, "clipped_sample_count": 30}
            )
        }
    )


def test_normalizing_a_clipped_source_warns(
    plan: ProcessingPlan, analysis: AnalysisDocument
) -> None:
    clipped = clipped_analysis(analysis)
    assert "normalize-clipped-source" in codes(validate_plan(plan, analysis=clipped))


def test_a_clipped_source_is_not_flagged_when_the_gain_is_negative(
    plan: ProcessingPlan, analysis: AnalysisDocument
) -> None:
    """Turning a clipped capture *down* amplifies nothing, so there is nothing to
    warn about — the old check fired on the mode alone and was simply wrong."""
    assert analysis.peaks is not None
    target = analysis.peaks.peak_db - 6.0
    quieter = mutated(plan, lambda payload: payload["normalize"].update(target_db=target))
    findings = codes(validate_plan(quieter, analysis=clipped_analysis(analysis)))
    assert "normalize-clipped-source" not in findings


@pytest.mark.parametrize("mode", ["album_rms", "album_gated_rms"])
def test_an_rms_target_without_a_peak_ceiling_warns(plan: ProcessingPlan, mode: str) -> None:
    uncapped = mutated(plan, lambda payload: payload["normalize"].update(mode=mode))
    assert "rms-without-peak-ceiling" in codes(validate_plan(uncapped))


def test_an_rms_target_with_a_peak_ceiling_is_accepted(plan: ProcessingPlan) -> None:
    with_ceiling = mutated(
        plan,
        lambda payload: payload["normalize"].update(
            mode="album_gated_rms", target_db=-18.0, peak_ceiling_db=-1.0
        ),
    )
    assert "rms-without-peak-ceiling" not in codes(validate_plan(with_ceiling))


def test_the_ungated_rms_mode_says_what_it_measures(plan: ProcessingPlan) -> None:
    ungated = mutated(
        plan,
        lambda payload: payload["normalize"].update(mode="album_rms", peak_ceiling_db=-1.0),
    )
    assert "ungated-rms" in codes(validate_plan(ungated))
    gated = mutated(
        plan,
        lambda payload: payload["normalize"].update(mode="album_gated_rms", peak_ceiling_db=-1.0),
    )
    assert "ungated-rms" not in codes(validate_plan(gated))


def test_a_ceiling_at_full_scale_warns_about_headroom(plan: ProcessingPlan) -> None:
    at_zero = mutated(plan, lambda payload: payload["normalize"].update(target_db=0.0))
    findings = [f for f in validate_plan(at_zero) if f.code == "no-headroom"]
    assert [f.location for f in findings] == ["normalize.target_db"]

    explicit = mutated(
        plan,
        lambda payload: payload["normalize"].update(
            mode="album_gated_rms", target_db=-18.0, peak_ceiling_db=0.0
        ),
    )
    findings = [f for f in validate_plan(explicit) if f.code == "no-headroom"]
    assert [f.location for f in findings] == ["normalize.peak_ceiling_db"]

    # An RMS target is a level, not a ceiling, so it says nothing about headroom.
    quiet_target = mutated(
        plan,
        lambda payload: payload["normalize"].update(
            mode="album_gated_rms", target_db=0.0, peak_ceiling_db=-1.0
        ),
    )
    assert "no-headroom" not in codes(validate_plan(quiet_target))


def test_a_gain_that_pushes_the_true_peak_past_full_scale_warns(
    plan: ProcessingPlan, analysis: AnalysisDocument
) -> None:
    assert analysis.peaks is not None
    loud = mutated(
        plan,
        lambda payload: payload["normalize"].update(mode="album_rms", target_db=0.0),
    )
    assert "true-peak-over-full-scale" in codes(validate_plan(loud, analysis=analysis))
    # A ceiling makes the executor cap the gain, so the warning has nothing to add.
    guarded = mutated(
        plan,
        lambda payload: payload["normalize"].update(
            mode="album_rms", target_db=0.0, peak_ceiling_db=-1.0
        ),
    )
    assert "true-peak-over-full-scale" not in codes(validate_plan(guarded, analysis=analysis))


def test_thin_true_peak_headroom_is_informational(
    plan: ProcessingPlan, analysis: AnalysisDocument
) -> None:
    assert analysis.peaks is not None
    # Force a wide inter-sample margin: the sample peak target is then met while
    # the reconstructed waveform lands well above it.
    wide = analysis.model_copy(
        update={
            "peaks": analysis.peaks.model_copy(
                update={"true_peak_db": analysis.peaks.peak_db + 0.8}
            )
        }
    )
    findings = {f.code: f.severity for f in validate_plan(plan, analysis=wide)}
    assert findings.get("thin-true-peak-headroom") == "info"


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


# --------------------------------------------------------------------------- #
# prefilter
# --------------------------------------------------------------------------- #
def prefiltered(plan: ProcessingPlan, **section: Any) -> ProcessingPlan:
    def replace(payload: dict[str, Any]) -> None:
        payload["prefilter"] = {"enabled": True, "engine": "native", **section}

    return mutated(plan, replace)


def test_an_absent_prefilter_section_is_valid_and_silent(plan: ProcessingPlan) -> None:
    """A pre-3.3 plan has no prefilter key at all and must still lint clean."""
    payload = plan.model_dump(mode="json")
    payload.pop("prefilter")
    revived = ProcessingPlan.model_validate(payload)
    assert revived.prefilter.enabled is False
    assert validate_plan(revived) == []


def test_prefilter_enabled_with_nothing_switched_on_warns(plan: ProcessingPlan) -> None:
    findings = validate_plan(prefiltered(plan, dc_block=False, highpass_hz=None))
    assert "prefilter-no-op" in codes(findings)


def test_a_cutoff_in_the_cited_band_reports_nothing(plan: ProcessingPlan) -> None:
    for cutoff in (20.0, 25.0, 30.0):
        assert codes(validate_plan(prefiltered(plan, highpass_hz=cutoff))) == set()


def test_a_cutoff_into_the_musical_bass_warns(plan: ProcessingPlan) -> None:
    findings = validate_plan(prefiltered(plan, highpass_hz=80.0))
    assert "subsonic-cutoff-high" in codes(findings)
    assert not [f for f in findings if f.severity == "error"]


def test_a_cutoff_below_the_cited_band_is_only_an_observation(plan: ProcessingPlan) -> None:
    findings = validate_plan(prefiltered(plan, highpass_hz=5.0))
    assert "subsonic-cutoff-outside-band" in codes(findings)
    assert [f.severity for f in findings] == ["info"]


def test_prefilter_engine_capability_is_checked(plan: ProcessingPlan) -> None:
    broken = prefiltered(plan, highpass_hz=25.0)
    broken = broken.model_copy(
        update={"prefilter": broken.prefilter.model_copy(update={"engine": "ffmpeg"})}
    )
    assert "engine-capability" in codes(validate_plan(broken))


def test_a_disabled_prefilter_is_not_checked_for_engines(plan: ProcessingPlan) -> None:
    def disable(payload: dict[str, Any]) -> None:
        payload["prefilter"] = {"enabled": False, "engine": "nope", "highpass_hz": 900.0}

    assert codes(validate_plan(mutated(plan, disable))) == set()


# --------------------------------------------------------------------------- #
# decrackle
# --------------------------------------------------------------------------- #
def decrackled(plan: ProcessingPlan, **section: Any) -> ProcessingPlan:
    def replace(payload: dict[str, Any]) -> None:
        payload["decrackle"] = {"enabled": True, "engine": "native", **section}

    return mutated(plan, replace)


def test_an_absent_decrackle_section_is_valid_and_silent(plan: ProcessingPlan) -> None:
    payload = plan.model_dump(mode="json")
    payload.pop("decrackle")
    revived = ProcessingPlan.model_validate(payload)
    assert revived.decrackle.enabled is False
    assert validate_plan(revived) == []


def test_decrackle_without_a_threshold_is_fatal(plan: ProcessingPlan) -> None:
    findings = validate_plan(decrackled(plan))
    assert "decrackle-without-threshold" in codes(findings)
    with pytest.raises(PlanValidationError, match="not executable"):
        raise_for_errors(findings)


def test_a_decrackle_width_wide_enough_to_be_clicks_warns(plan: ProcessingPlan) -> None:
    findings = validate_plan(decrackled(plan, threshold=5.0, max_event_width_samples=8))
    assert "decrackle-width-is-clicks" in codes(findings)


def test_decrackle_without_declick_is_only_an_observation(plan: ProcessingPlan) -> None:
    def both(payload: dict[str, Any]) -> None:
        payload["decrackle"] = {"enabled": True, "engine": "native", "threshold": 5.0}
        payload["declick"]["enabled"] = False

    findings = validate_plan(mutated(plan, both))
    assert "decrackle-without-declick" in codes(findings)
    assert not [f for f in findings if f.severity == "error"]


def test_pitch_protection_together_with_decrackle_warns(plan: ProcessingPlan) -> None:
    """The manual says the combination "may seriously impair de-crackling"."""

    def both(payload: dict[str, Any]) -> None:
        payload["decrackle"] = {"enabled": True, "engine": "native", "threshold": 5.0}
        payload["declick"]["params"] = {"confirm_k": 3.0}

    assert "decrackle-with-pitch-protection" in codes(validate_plan(mutated(plan, both)))


def test_a_sane_decrackle_section_reports_nothing(plan: ProcessingPlan) -> None:
    assert codes(validate_plan(decrackled(plan, threshold=5.0))) == set()


# --------------------------------------------------------------------------- #
# mono merge
# --------------------------------------------------------------------------- #
def folded(plan: ProcessingPlan, **section: Any) -> ProcessingPlan:
    def replace(payload: dict[str, Any]) -> None:
        payload["mono_merge"] = {"enabled": True, "engine": "native", **section}

    return mutated(plan, replace)


def test_an_absent_mono_merge_section_is_valid_and_silent(plan: ProcessingPlan) -> None:
    payload = plan.model_dump(mode="json")
    payload.pop("mono_merge")
    revived = ProcessingPlan.model_validate(payload)
    assert revived.mono_merge.enabled is False
    assert validate_plan(revived) == []


def test_a_sane_mono_merge_section_reports_nothing(plan: ProcessingPlan) -> None:
    assert codes(validate_plan(folded(plan))) == set()


def test_a_short_level_window_warns(plan: ProcessingPlan) -> None:
    findings = validate_plan(folded(plan, level_window_seconds=0.01))
    assert "mono-merge-window-short" in codes(findings)


def test_taking_one_wall_is_not_held_to_the_window_rule(plan: ProcessingPlan) -> None:
    """There is no level tracker on a strategy that copies a channel."""
    findings = validate_plan(folded(plan, strategy="left", level_window_seconds=0.001))
    assert "mono-merge-window-short" not in codes(findings)


def test_merging_a_source_with_one_channel_warns(plan: ProcessingPlan) -> None:
    def one_channel(payload: dict[str, Any]) -> None:
        payload["mono_merge"] = {"enabled": True, "engine": "native"}
        payload["source"]["channels"] = 1

    assert "mono-merge-without-two-walls" in codes(validate_plan(mutated(plan, one_channel)))


def with_correlation(analysis: AnalysisDocument, value: float) -> AnalysisDocument:
    recording_info = analysis.recording_info
    assert recording_info is not None, "the fixture analysis must carry recording_info"
    return analysis.model_copy(
        update={"recording_info": recording_info.model_copy(update={"channel_correlation": value})}
    )


def test_merging_stereo_material_warns_when_the_analysis_is_available(
    plan: ProcessingPlan, recording: SyntheticRecording, analysis: AnalysisDocument
) -> None:
    """The one catastrophic mistake this stage can make, and lint is the only
    place that can see both the plan and the measurement."""
    stereo = with_correlation(analysis, 0.42)
    findings = validate_plan(folded(plan), audio_path=recording.path, analysis=stereo)
    assert "mono-merge-on-stereo-material" in codes(findings)


def test_a_genuinely_mono_capture_does_not_warn(
    plan: ProcessingPlan, recording: SyntheticRecording, analysis: AnalysisDocument
) -> None:
    mono = with_correlation(analysis, 0.999)
    findings = validate_plan(folded(plan), audio_path=recording.path, analysis=mono)
    assert "mono-merge-on-stereo-material" not in codes(findings)


# --------------------------------------------------------------------------- #
# speed
# --------------------------------------------------------------------------- #
def sped(plan: ProcessingPlan, **section: Any) -> ProcessingPlan:
    def replace(payload: dict[str, Any]) -> None:
        payload["speed"] = {"enabled": True, "engine": "native", **section}

    return mutated(plan, replace)


def test_an_absent_speed_section_is_valid_and_silent(plan: ProcessingPlan) -> None:
    payload = plan.model_dump(mode="json")
    payload.pop("speed")
    revived = ProcessingPlan.model_validate(payload)
    assert revived.speed.enabled is False
    assert validate_plan(revived) == []


def test_speed_without_both_rpm_is_fatal(plan: ProcessingPlan) -> None:
    findings = validate_plan(sped(plan, played_rpm=78.0))
    assert "speed-without-both-rpm" in codes(findings)
    with pytest.raises(PlanValidationError, match="not executable"):
        raise_for_errors(findings)


def test_a_speed_pair_that_changes_nothing_warns(plan: ProcessingPlan) -> None:
    findings = validate_plan(sped(plan, played_rpm=33.3333, intended_rpm=33.3333))
    assert "speed-no-op" in codes(findings)


def test_a_gross_speed_correction_warns(plan: ProcessingPlan) -> None:
    """45 played as 33 is not a trim; it is a different transfer."""
    findings = validate_plan(sped(plan, played_rpm=45.0, intended_rpm=33.3333))
    assert "speed-correction-is-gross" in codes(findings)


def test_a_small_speed_correction_reports_nothing(plan: ProcessingPlan) -> None:
    assert codes(validate_plan(sped(plan, played_rpm=33.4, intended_rpm=33.3333))) == set()


def test_correcting_speed_and_resampling_is_reported(plan: ProcessingPlan) -> None:
    def both(payload: dict[str, Any]) -> None:
        payload["speed"] = {
            "enabled": True,
            "engine": "native",
            "played_rpm": 33.4,
            "intended_rpm": 33.3333,
        }
        payload["export"]["sample_rate"] = 48000

    findings = validate_plan(mutated(plan, both))
    assert "speed-and-resample" in codes(findings)

"""End to end: measure, plan, execute, and prove the result is reproducible."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from tests.conftest import build_plan
from tests.fixtures.synth import SyntheticRecording, write_recording
from vinyl_process.analyzer import run_analysis
from vinyl_process.errors import ExecutionError, PlanValidationError
from vinyl_process.executor import MANIFEST_NAME, execute_plan
from vinyl_process.hashing import digest_file
from vinyl_process.models.analysis import AnalysisDocument
from vinyl_process.models.manifest import ExecutionManifest
from vinyl_process.models.plan import ProcessingPlan
from vinyl_process.signal_ops import loudness_block_powers, loudness_of_blocks


def run(
    plan: ProcessingPlan, recording: SyntheticRecording, output_dir: Path, **kwargs: Any
) -> ExecutionManifest:
    return execute_plan(
        plan,
        output_dir,
        source_path=recording.path,
        plan_path="processing_plan.json",
        plan_digest="d" * 64,
        **kwargs,
    )


def peak_db(path: Path) -> float:
    samples, _rate = sf.read(str(path), dtype="float64", always_2d=True)
    return float(20 * np.log10(np.max(np.abs(samples))))


def mutated(plan: ProcessingPlan, mutate) -> ProcessingPlan:
    payload = plan.model_dump(mode="json")
    mutate(payload)
    return ProcessingPlan.model_validate(payload)


# --------------------------------------------------------------------------- #
def test_pipeline_produces_a_tagged_album(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    import mutagen

    manifest = run(plan, recording, tmp_path / "album")

    assert len(manifest.outputs) == len(recording.programme)
    for output in manifest.outputs:
        path = Path(output.path)
        assert path.is_file()
        assert path.suffix == ".flac"
        assert output.tagged
        assert output.sha256 == digest_file(path)
        assert output.bytes == path.stat().st_size

    first = Path(manifest.outputs[0].path)
    assert first.name == "01 - Movement 1.flac"
    tags = mutagen.File(str(first)).tags
    assert tags["album"] == ["Test Pressing"]
    assert tags["title"] == ["Movement 1"]
    assert tags["tracknumber"] == ["1"]
    assert tags["tracktotal"] == [str(len(recording.programme))]
    assert (tmp_path / "album" / MANIFEST_NAME).is_file()


def test_executing_the_same_plan_twice_is_bit_identical(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    first = run(plan, recording, tmp_path / "one")
    second = run(plan, recording, tmp_path / "two")

    assert first.output_digests() == second.output_digests()
    assert first.run_key == second.run_key
    assert first.applied_gain_db == second.applied_gain_db


def test_manifest_records_every_stage_and_the_environment(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    manifest = run(plan, recording, tmp_path / "album")

    stages = {record.stage: record for record in manifest.stages}
    assert set(stages) == {
        "prefilter",
        "declick",
        "decrackle",
        "split",
        "normalize",
        "resample",
        "export",
        "metadata",
    }
    # The receipt lists the stages in the order they ran, pre-split phase first.
    assert [record.stage for record in manifest.stages][:4] == [
        "prefilter",
        "declick",
        "decrackle",
        "split",
    ]
    assert stages["prefilter"].status == "skipped"
    assert stages["decrackle"].status == "skipped"
    # A repair stage says how much of the audio it actually changed.
    assert "repaired" in stages["declick"].detail
    assert stages["split"].status == "applied"
    assert stages["split"].engine == "native"
    assert stages["split"].engine_version
    assert stages["resample"].status == "skipped"
    assert all(record.params_digest for record in manifest.stages if record.status == "applied")
    assert manifest.source.sha256 == digest_file(recording.path)
    assert manifest.plan.sha256 == "d" * 64
    assert {"python", "numpy", "scipy", "soundfile", "libsndfile"} <= set(manifest.environment)


def test_album_normalization_preserves_relative_track_levels(tmp_path: Path) -> None:
    """The point of album-wide gain: track 2 stays 6 dB below track 1."""
    recording = write_recording(tmp_path / "quiet-second.wav", level_scales=(1.0, 0.5))
    analysis = run_analysis(recording.path)
    plan = build_plan(recording, analysis)

    manifest = run(plan, recording, tmp_path / "album")
    levels = [peak_db(Path(output.path)) for output in manifest.outputs]

    assert levels[0] == pytest.approx(-1.0, abs=0.01)
    assert levels[1] == pytest.approx(-1.0 + 20 * np.log10(0.5), abs=0.05)
    assert manifest.applied_gain_db is not None


def test_track_normalization_flattens_them(tmp_path: Path) -> None:
    recording = write_recording(tmp_path / "quiet-second.wav", level_scales=(1.0, 0.5))
    analysis = run_analysis(recording.path)
    plan = mutated(
        build_plan(recording, analysis),
        lambda payload: payload["normalize"].update(mode="track_peak"),
    )

    manifest = run(plan, recording, tmp_path / "album")
    for output in manifest.outputs:
        assert peak_db(Path(output.path)) == pytest.approx(-1.0, abs=0.01)
    # A single album gain does not exist in this mode, so the manifest says so.
    assert manifest.applied_gain_db is None
    assert "track_peak" in next(s for s in manifest.stages if s.stage == "normalize").detail


def test_gated_normalization_ignores_the_silence_a_plain_rms_counts(tmp_path: Path) -> None:
    """One track spanning the whole side — lead-in, gaps, run-out and all, which
    is what an unsplit rip or a loose cut looks like. The ungated average counts
    every silent second as programme and asks for a gain the music does not need.
    """
    recording = write_recording(tmp_path / "gappy.wav")
    analysis = run_analysis(recording.path)

    def whole_side(payload: dict[str, Any], mode: str) -> None:
        payload["split"]["tracks"] = [
            {"index": 1, "start_sample": 0, "end_sample": recording.num_frames}
        ]
        payload["metadata"]["tracks"] = [{"index": 1, "title": "Side A"}]
        payload["normalize"].update(mode=mode, target_db=-14.0, peak_ceiling_db=-1.0)

    base = build_plan(recording, analysis)
    gated = run(
        mutated(base, lambda p: whole_side(p, "album_gated_rms")), recording, tmp_path / "gated"
    )
    plain = run(mutated(base, lambda p: whole_side(p, "album_rms")), recording, tmp_path / "plain")
    assert gated.applied_gain_db is not None
    assert plain.applied_gain_db is not None
    assert plain.applied_gain_db > gated.applied_gain_db + 1.0


def test_the_peak_ceiling_caps_a_gain_the_level_target_asked_for(tmp_path: Path) -> None:
    recording = write_recording(tmp_path / "ceiling.wav")
    analysis = run_analysis(recording.path)
    plan = mutated(
        build_plan(recording, analysis),
        lambda payload: payload["normalize"].update(
            mode="album_gated_rms", target_db=0.0, peak_ceiling_db=-1.0
        ),
    )
    manifest = run(plan, recording, tmp_path / "album")

    assert manifest.applied_true_peak_db is not None
    assert manifest.applied_true_peak_db == pytest.approx(-1.0, abs=0.01)
    assert any("peak_ceiling_db" in warning for warning in manifest.warnings)
    for output in manifest.outputs:
        assert peak_db(Path(output.path)) <= -1.0


def test_without_a_ceiling_a_clipped_export_still_reaches_the_receipt(tmp_path: Path) -> None:
    """save_audio clamps, which is right; doing it silently was not."""
    recording = write_recording(tmp_path / "clipping.wav")
    analysis = run_analysis(recording.path)
    plan = mutated(
        build_plan(recording, analysis),
        lambda payload: payload["normalize"].update(mode="album_rms", target_db=0.0),
    )
    manifest = run(plan, recording, tmp_path / "album")

    assert manifest.applied_true_peak_db is not None
    assert manifest.applied_true_peak_db > 0.0
    assert any("clips" in warning for warning in manifest.warnings)


def test_the_manifest_records_the_gain_it_actually_applied(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    """Re-applying applied_gain_db must reproduce the export, so the recorded
    value has to be the one that ran — not a rounding of it."""
    manifest = run(plan, recording, tmp_path / "album")
    assert manifest.applied_gain_db is not None
    assert manifest.applied_track_gains_db is None

    explicit = mutated(
        plan,
        lambda payload: payload["normalize"].update(mode="album_peak", target_db=round(-1.0, 4)),
    )
    again = run(explicit, recording, tmp_path / "again")
    assert again.applied_gain_db == manifest.applied_gain_db
    assert again.output_digests() == manifest.output_digests()


def test_track_peak_records_every_gain_it_applied(tmp_path: Path) -> None:
    recording = write_recording(tmp_path / "quiet-second.wav", level_scales=(1.0, 0.5))
    analysis = run_analysis(recording.path)
    plan = mutated(
        build_plan(recording, analysis),
        lambda payload: payload["normalize"].update(mode="track_peak"),
    )
    manifest = run(plan, recording, tmp_path / "album")

    gains = manifest.applied_track_gains_db
    assert gains is not None
    assert len(gains) == len(manifest.outputs)
    # The quiet track needed 6 dB more than the loud one to reach the same peak.
    assert gains[1] - gains[0] == pytest.approx(6.02, abs=0.1)


def test_declick_removes_clicks_from_the_exported_audio(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    with_repair = run(plan, recording, tmp_path / "repaired")
    without = run(
        mutated(plan, lambda payload: payload["declick"].update(enabled=False)),
        recording,
        tmp_path / "damaged",
    )

    repaired_clicks = run_analysis(with_repair.outputs[0].path, analyzers=["clicks"]).clicks
    damaged_clicks = run_analysis(without.outputs[0].path, analyzers=["clicks"]).clicks
    assert repaired_clicks is not None
    assert damaged_clicks is not None

    def loud(section, floor_db: float = -30.0) -> int:
        edges = section.amplitude_histogram.bin_edges
        return sum(
            count
            for count, low in zip(section.amplitude_histogram.counts, edges, strict=False)
            if low >= floor_db
        )

    # Counting *detections* is the wrong measure: the detector's threshold is
    # relative, so once the loud clicks are gone it starts resolving the repair's
    # own -60 dB seams. What must hold is that nothing audible is left.
    assert loud(damaged_clicks) >= 3
    assert loud(repaired_clicks) == 0
    assert sum(repaired_clicks.amplitude_histogram.counts) == repaired_clicks.count


def test_fades_reach_the_edges_of_every_track(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    manifest = run(plan, recording, tmp_path / "album")
    for output in manifest.outputs:
        samples, _rate = sf.read(output.path, dtype="float64", always_2d=True)
        assert abs(samples[0, 0]) < 1e-6
        assert abs(samples[-1, 0]) < 1e-6


def test_disabled_stages_are_skipped_not_silently_applied(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    def disable_everything(payload: dict[str, Any]) -> None:
        payload["split"]["enabled"] = False
        payload["declick"]["enabled"] = False
        payload["normalize"]["mode"] = "none"
        payload["metadata"]["enabled"] = False

    manifest = run(mutated(plan, disable_everything), recording, tmp_path / "album")
    statuses = {record.stage: record.status for record in manifest.stages}
    assert statuses["split"] == "skipped"
    assert statuses["declick"] == "skipped"
    assert statuses["normalize"] == "skipped"
    assert statuses["metadata"] == "skipped"

    assert len(manifest.outputs) == 1
    assert manifest.outputs[0].num_samples == recording.num_frames
    assert not manifest.outputs[0].tagged
    assert Path(manifest.outputs[0].path).name == "01 - Movement 1.flac"


def test_a_mismatched_source_is_refused_and_can_be_overridden(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    samples, sample_rate = sf.read(str(recording.path), always_2d=True)

    # Same length, one different sample: only the digest can tell them apart.
    edited = tmp_path / "edited.wav"
    altered = samples.copy()
    altered[1000, 0] *= 0.5
    sf.write(str(edited), altered, sample_rate, subtype="PCM_24")

    with pytest.raises(PlanValidationError, match="source-mismatch"):
        execute_plan(plan, tmp_path / "album", source_path=edited)
    assert not (tmp_path / "album").exists(), "nothing may be written before validation passes"

    manifest = execute_plan(plan, tmp_path / "forced", source_path=edited, verify_source=False)
    assert any("verification was disabled" in warning for warning in manifest.warnings)


def test_a_truncated_source_is_refused_even_without_digest_verification(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    """--no-verify-source must not let the cuts run off the end of the file."""
    samples, sample_rate = sf.read(str(recording.path), always_2d=True)
    truncated = tmp_path / "truncated.wav"
    sf.write(str(truncated), samples[: len(samples) // 2], sample_rate, subtype="PCM_24")

    with pytest.raises(PlanValidationError, match="source-length-mismatch"):
        execute_plan(plan, tmp_path / "album", source_path=truncated, verify_source=False)


def test_existing_files_are_protected_unless_overwrite_is_requested(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    album = tmp_path / "album"
    run(plan, recording, album)
    with pytest.raises(ExecutionError, match="already exists"):
        run(plan, recording, album)
    run(plan, recording, album, overwrite=True)


def test_an_unexecutable_plan_fails_before_touching_the_output_directory(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    broken = mutated(plan, lambda payload: payload["declick"].update(engine="nope"))
    with pytest.raises(PlanValidationError, match="unknown-engine"):
        run(broken, recording, tmp_path / "album")
    assert not (tmp_path / "album").exists()


@pytest.mark.parametrize(("audio_format", "bit_depth"), [("wav", 16), ("aiff", 24)])
def test_other_export_targets_are_written_and_tagged(
    plan: ProcessingPlan,
    recording: SyntheticRecording,
    tmp_path: Path,
    audio_format: str,
    bit_depth: int,
) -> None:
    import mutagen

    exported = mutated(
        plan,
        lambda payload: payload["export"].update(format=audio_format, bit_depth=bit_depth),
    )
    manifest = run(exported, recording, tmp_path / "album")
    first = Path(manifest.outputs[0].path)
    assert first.suffix == f".{audio_format}"
    assert mutagen.File(str(first)).tags["TALB"].text == ["Test Pressing"]


def test_dithered_export_is_reproducible(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    def to_dithered_16_bit(payload: dict[str, Any]) -> None:
        payload["export"].update(format="wav", bit_depth=16, dither="tpdf", dither_seed=42)

    dithered = mutated(plan, to_dithered_16_bit)
    first = run(dithered, recording, tmp_path / "one")
    second = run(dithered, recording, tmp_path / "two")
    assert first.output_digests() == second.output_digests()

    def reroll(payload: dict[str, Any]) -> None:
        to_dithered_16_bit(payload)
        payload["export"]["dither_seed"] = 43

    third = run(mutated(plan, reroll), recording, tmp_path / "three")
    assert third.output_digests() != first.output_digests()


def test_resampling_is_applied_and_recorded(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    resampled = mutated(plan, lambda payload: payload["export"].update(sample_rate=22050))
    manifest = run(resampled, recording, tmp_path / "album")

    stage = next(record for record in manifest.stages if record.stage == "resample")
    assert stage.status == "applied"
    assert "22050" in stage.detail
    for output in manifest.outputs:
        assert output.sample_rate == 22050
        assert sf.info(output.path).samplerate == 22050


def test_the_analysis_document_is_never_needed_to_execute(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path, analysis: AnalysisDocument
) -> None:
    """The plan is the complete record: executing must not consult measurements."""
    import vinyl_process.executor as executor_module

    source = Path(executor_module.__file__).read_text(encoding="utf-8")
    assert "analyzer" not in source
    assert "AnalysisDocument" not in source
    run(plan, recording, tmp_path / "album")  # and it still works


# --------------------------------------------------------------------------- #
# the pre-split phase
# --------------------------------------------------------------------------- #
def test_prefilter_runs_before_the_cuts_and_recovers_headroom(
    recording: SyntheticRecording, analysis: AnalysisDocument, tmp_path: Path
) -> None:
    """A warped transfer: the rumble eats the headroom a peak mode would use.

    The filter is the whole difference between the two runs, so the gain the
    second one finds is the headroom the stage bought.
    """
    warped = tmp_path / "warped.flac"
    samples, rate = sf.read(str(recording.path), dtype="float64", always_2d=True)
    t = np.arange(samples.shape[0]) / rate
    rumble = 0.25 * np.sin(2 * np.pi * 4.0 * t)[:, None]
    sf.write(str(warped), samples + rumble, rate, subtype="PCM_24")

    warped_analysis = run_analysis(warped)
    plain = build_plan(recording, warped_analysis)
    plain = plain.model_copy(update={"source": warped_analysis.source})

    def with_prefilter(payload: dict[str, Any]) -> ProcessingPlan:
        payload["prefilter"] = {
            "enabled": True,
            "engine": "native",
            "dc_block": True,
            "highpass_hz": 30.0,
            "highpass_rolloff_db_per_octave": 24,
        }
        return ProcessingPlan.model_validate(payload)

    filtered = with_prefilter(plain.model_dump(mode="json"))

    before = execute_plan(plain, tmp_path / "plain", source_path=warped, plan_digest="a" * 64)
    after = execute_plan(filtered, tmp_path / "filtered", source_path=warped, plan_digest="b" * 64)

    stages = {record.stage: record for record in after.stages}
    assert stages["prefilter"].status == "applied"
    assert stages["prefilter"].engine == "native"
    assert "highpass=30 Hz @ 24 dB/oct" in stages["prefilter"].detail
    assert "dc_block" in stages["prefilter"].detail
    assert stages["prefilter"].params_digest

    # The receipt proves the position, not just the presence.
    order = [record.stage for record in after.stages]
    assert order.index("prefilter") < order.index("declick") < order.index("split")

    # The rumble was inflating the peak, so the filtered run finds more gain.
    assert after.applied_gain_db is not None
    assert before.applied_gain_db is not None
    assert after.applied_gain_db > before.applied_gain_db + 1.0
    # ...and both still hit the target, because album_peak is a peak mode.
    assert after.applied_true_peak_db is not None
    assert after.applied_true_peak_db < 0.0

    # Re-measure the exported audio: the filter has to show up in the same
    # quantity that argued for it, or the stage claimed something it did not do.
    def rumble_db(manifest: ExecutionManifest) -> float:
        section = run_analysis(Path(manifest.outputs[0].path), analyzers=["spectral"]).spectral
        assert section is not None
        return section.rumble_db

    assert rumble_db(after) < rumble_db(before) - 6.0


def test_prefilter_enabled_but_asking_for_nothing_says_so(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    payload = plan.model_dump(mode="json")
    payload["prefilter"] = {"enabled": True, "engine": "native"}
    noop = ProcessingPlan.model_validate(payload)

    manifest = run(noop, recording, tmp_path / "album")
    stages = {record.stage: record for record in manifest.stages}
    assert stages["prefilter"].status == "skipped"
    assert any("asks for nothing" in warning for warning in manifest.warnings)


def test_a_prefiltered_run_reproduces_bit_for_bit(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    payload = plan.model_dump(mode="json")
    payload["prefilter"] = {"enabled": True, "engine": "native", "highpass_hz": 25.0}
    filtered = ProcessingPlan.model_validate(payload)

    first = run(filtered, recording, tmp_path / "one")
    second = run(filtered, recording, tmp_path / "two")
    assert first.output_digests() == second.output_digests()


def test_declick_now_sees_the_whole_side_rather_than_faded_tracks(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    """Repair happens pre-split, so a track's fades are applied *after* it.

    The observable consequence: with declick on, the first and last samples of an
    exported track are still exactly the fade's own ramp — zero at the very edge —
    rather than something repair touched afterwards.
    """
    manifest = run(plan, recording, tmp_path / "album")
    stages = {record.stage: record for record in manifest.stages}
    assert stages["declick"].status == "applied"
    assert "pre-split" in stages["declick"].detail

    first_output = Path(manifest.outputs[0].path)
    samples, _rate = sf.read(str(first_output), dtype="float64", always_2d=True)
    assert np.allclose(samples[0], 0.0, atol=1e-6)
    assert np.allclose(samples[-1], 0.0, atol=1e-6)


def test_decrackle_runs_after_declick_and_reports_its_repair_rate(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    """The receipt has to carry the figure the practitioner band is stated in."""
    payload = plan.model_dump(mode="json")
    payload["decrackle"] = {"enabled": True, "engine": "native", "threshold": 3.0}
    crackly = ProcessingPlan.model_validate(payload)

    manifest = run(crackly, recording, tmp_path / "album")
    order = [record.stage for record in manifest.stages]
    assert order.index("declick") < order.index("decrackle") < order.index("split")

    stages = {record.stage: record for record in manifest.stages}
    assert stages["decrackle"].status == "applied"
    assert stages["decrackle"].engine == "native"
    assert "repaired" in stages["decrackle"].detail
    assert "1 in " in stages["decrackle"].detail or "nothing changed" in (
        stages["decrackle"].detail
    )


def test_a_decrackled_run_reproduces_bit_for_bit(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    payload = plan.model_dump(mode="json")
    payload["decrackle"] = {"enabled": True, "engine": "native", "threshold": 3.0}
    crackly = ProcessingPlan.model_validate(payload)
    first = run(crackly, recording, tmp_path / "one")
    second = run(crackly, recording, tmp_path / "two")
    assert first.output_digests() == second.output_digests()


def test_album_lufs_hits_its_target_and_is_capped_by_the_ceiling(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    """The mode end to end: pooled across tracks, and held under the ceiling."""
    payload = plan.model_dump(mode="json")
    payload["normalize"] = {
        "engine": "native",
        "mode": "album_lufs",
        "target_db": -23.0,
        "peak_ceiling_db": -1.0,
    }
    lufs = ProcessingPlan.model_validate(payload)

    manifest = run(lufs, recording, tmp_path / "album")
    stages = {record.stage: record for record in manifest.stages}
    assert "mode=album_lufs" in stages["normalize"].detail

    # Re-measure the exported album the way the mode measures it: pool every
    # track's gating blocks, then gate. It must land on the target, unless the
    # ceiling capped the gain — in which case the manifest says so.
    powers = []
    for output in manifest.outputs:
        samples, rate = sf.read(output.path, dtype="float64", always_2d=True)
        powers.append(loudness_block_powers(samples, rate))
    measured = loudness_of_blocks(np.concatenate(powers))

    capped = any("peak_ceiling_db" in warning for warning in manifest.warnings)
    if capped:
        assert measured < -23.0
        assert manifest.applied_true_peak_db is not None
        assert manifest.applied_true_peak_db <= -1.0 + 0.01
    else:
        assert measured == pytest.approx(-23.0, abs=0.2)


def test_album_lufs_pools_the_album_rather_than_measuring_each_track(
    plan: ProcessingPlan, recording: SyntheticRecording, tmp_path: Path
) -> None:
    """One gain for the side, so the relative levels between tracks survive."""
    payload = plan.model_dump(mode="json")
    payload["normalize"] = {
        "engine": "native",
        "mode": "album_lufs",
        "target_db": -23.0,
        "peak_ceiling_db": -1.0,
    }
    manifest = run(ProcessingPlan.model_validate(payload), recording, tmp_path / "album")
    assert manifest.applied_gain_db is not None
    assert manifest.applied_track_gains_db is None

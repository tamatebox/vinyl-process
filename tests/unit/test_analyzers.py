"""Analyzer accuracy: every measurement is checked against known ground truth."""

from __future__ import annotations

import dataclasses
import itertools

import numpy as np
import pytest

from tests.fixtures.synth import CLICK_AMPLITUDE, SURFACE_NOISE_AMPLITUDE, SyntheticRecording
from vinyl_process.analyzer import all_analyzers, run_analysis
from vinyl_process.analyzer import registry as registry_module
from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.config import Config
from vinyl_process.errors import AnalysisError
from vinyl_process.models.analysis import AnalysisDocument
from vinyl_process.models.common import Section

TOLERANCE_SECONDS = 0.35


def test_every_section_is_present_and_stamped(analysis: AnalysisDocument) -> None:
    for name in AnalysisDocument.section_fields():
        section = getattr(analysis, name)
        assert section is not None, f"{name} was not produced"
        assert section.meta.analyzer == name
        assert section.meta.version
    assert all(run.status == "ok" for run in analysis.analyzers)
    assert analysis.config_digest


def test_parameters_are_recorded_for_reproducibility(analysis: AnalysisDocument) -> None:
    assert analysis.rms_profile is not None
    assert analysis.rms_profile.meta.params == {"window_seconds": 0.2, "hop_seconds": 0.1}


def test_recording_info_recovers_the_capture_characteristics(
    analysis: AnalysisDocument, recording: SyntheticRecording
) -> None:
    info = analysis.recording_info
    assert info is not None
    assert info.subtype == "PCM_24"
    assert info.bit_depth == 24
    assert info.channel_correlation == pytest.approx(1.0, abs=1e-3)
    # The fixture attenuates the right channel by 0.985.
    assert info.channel_balance_db == pytest.approx(-20 * np.log10(0.985), abs=0.05)
    assert max(abs(offset) for offset in info.dc_offset) < 1e-3


def test_surface_noise_matches_the_injected_noise_floor(analysis: AnalysisDocument) -> None:
    noise = analysis.surface_noise
    assert noise is not None
    expected_db = 20 * np.log10(SURFACE_NOISE_AMPLITUDE)
    assert noise.noise_floor_db == pytest.approx(expected_db, abs=6.0)
    assert noise.meta.confidence is not None
    assert noise.meta.confidence > 0.5


def test_silence_regions_match_the_generated_gaps(
    analysis: AnalysisDocument, recording: SyntheticRecording
) -> None:
    silence = analysis.silence
    assert silence is not None
    found = [
        (region.start_sample / recording.sample_rate, region.end_sample / recording.sample_rate)
        for region in silence.regions
    ]
    assert len(found) == len(recording.gaps)
    for (start, end), (expected_start, expected_end) in zip(found, recording.gaps, strict=True):
        assert start == pytest.approx(expected_start, abs=TOLERANCE_SECONDS)
        assert end == pytest.approx(expected_end, abs=TOLERANCE_SECONDS)


def test_lead_in_and_lead_out_are_detected(
    analysis: AnalysisDocument, recording: SyntheticRecording
) -> None:
    """Regression test: both used to be None because the edge regions never
    reached the exact final sample."""
    boundaries = analysis.boundaries
    assert boundaries is not None
    assert boundaries.lead_in_end_sample is not None
    assert boundaries.lead_out_start_sample is not None
    assert boundaries.lead_in_end_sample / recording.sample_rate == pytest.approx(
        recording.lead_in_end, abs=TOLERANCE_SECONDS
    )
    assert boundaries.lead_out_start_sample / recording.sample_rate == pytest.approx(
        recording.lead_out_start, abs=TOLERANCE_SECONDS
    )


def test_every_interior_gap_has_a_silence_candidate(
    analysis: AnalysisDocument, recording: SyntheticRecording
) -> None:
    boundaries = analysis.boundaries
    assert boundaries is not None
    silence_candidates = [c for c in boundaries.candidates if c.method == "silence"]
    assert len(silence_candidates) == len(recording.interior_gaps)
    for candidate, (start, end) in zip(silence_candidates, recording.interior_gaps, strict=True):
        seconds = candidate.sample / recording.sample_rate
        assert start < seconds < end
        assert candidate.confidence > 0.5


def test_candidates_come_from_several_methods_and_are_ordered(
    analysis: AnalysisDocument,
) -> None:
    boundaries = analysis.boundaries
    assert boundaries is not None
    samples = [candidate.sample for candidate in boundaries.candidates]
    assert samples == sorted(samples)
    assert len({candidate.method for candidate in boundaries.candidates}) >= 2


def test_spectral_change_candidates_are_de_clustered(analysis: AnalysisDocument) -> None:
    boundaries = analysis.boundaries
    assert boundaries is not None
    positions = sorted(c.sample for c in boundaries.candidates if c.method == "spectral_change")
    minimum_gap = 0.5 * 44100
    assert all(second - first >= minimum_gap for first, second in itertools.pairwise(positions))


def test_clicks_find_every_injected_click(
    analysis: AnalysisDocument, recording: SyntheticRecording
) -> None:
    clicks = analysis.clicks
    assert clicks is not None
    assert clicks.count >= len(recording.click_positions)
    for injected in recording.click_positions:
        assert any(
            abs(detected - injected) < 0.01 * recording.sample_rate
            for detected in clicks.positions_sample
        ), f"click at {injected} was not detected"


def test_click_histograms_are_well_formed_and_bin_the_injected_level(
    analysis: AnalysisDocument, recording: SyntheticRecording
) -> None:
    clicks = analysis.clicks
    assert clicks is not None
    for histogram in (clicks.amplitude_histogram, clicks.width_histogram):
        assert len(histogram.bin_edges) == len(histogram.counts) + 1
        assert sum(histogram.counts) == clicks.count
    assert clicks.amplitude_histogram.unit == "dBFS"
    assert clicks.width_histogram.unit == "ms"
    # The injected clicks sit around -7 dBFS, i.e. in the loudest populated bin.
    injected_db = 20 * np.log10(CLICK_AMPLITUDE)
    loudest_edge = clicks.amplitude_histogram.bin_edges[-2]
    assert injected_db > loudest_edge - 20


def test_click_density_covers_the_whole_recording(
    analysis: AnalysisDocument, recording: SyntheticRecording
) -> None:
    clicks = analysis.clicks
    assert clicks is not None
    expected_buckets = int(np.ceil(recording.num_frames / (recording.sample_rate * 60)))
    assert len(clicks.density_per_minute) == expected_buckets
    assert sum(clicks.density_per_minute) == clicks.count


def test_peaks_and_dynamic_range(analysis: AnalysisDocument, recording: SyntheticRecording) -> None:
    peaks = analysis.peaks
    dynamic_range = analysis.dynamic_range
    assert peaks is not None
    assert dynamic_range is not None
    assert peaks.peak_db == pytest.approx(20 * np.log10(recording.peak_amplitude), abs=0.05)
    assert 0 <= peaks.peak_sample < recording.num_frames
    assert peaks.crest_factor_db > 0
    assert dynamic_range.dr_estimate_db > 0
    assert (
        dynamic_range.percentiles.p05_db
        <= dynamic_range.percentiles.p50_db
        <= dynamic_range.percentiles.p95_db
    )


def test_clean_source_reports_no_clipping(analysis: AnalysisDocument) -> None:
    clipping = analysis.clipping
    assert clipping is not None
    assert clipping.clipped_sample_count == 0
    assert clipping.clipped_region_count == 0
    assert clipping.ratio == 0.0


def test_clipping_is_detected_when_present(tmp_path) -> None:
    import soundfile as sf

    from tests.fixtures.synth import write_recording

    recording = write_recording(tmp_path / "clipped.wav")
    samples, sample_rate = sf.read(str(recording.path), always_2d=True)
    samples[1000:1010] = 1.0
    sf.write(str(recording.path), samples, sample_rate, subtype="PCM_24")

    document = run_analysis(recording.path, analyzers=["clipping"])
    assert document.clipping is not None
    assert document.clipping.clipped_sample_count >= 10
    assert document.clipping.clipped_region_count == 1
    assert document.clipping.longest_run_samples >= 10
    assert any("clipping" in warning for warning in document.warnings)


def test_spectral_bands_stay_inside_nyquist(
    analysis: AnalysisDocument, recording: SyntheticRecording
) -> None:
    spectral = analysis.spectral
    assert spectral is not None
    nyquist = recording.sample_rate / 2
    assert spectral.bands
    for band in spectral.bands:
        assert band.low_hz < band.high_hz <= nyquist
    assert 0 < spectral.centroid_mean_hz < nyquist
    assert 0 < spectral.rolloff_mean_hz <= nyquist


def test_transients_are_sparse_for_sustained_material(analysis: AnalysisDocument) -> None:
    transients = analysis.transients
    assert transients is not None
    assert len(transients.density_per_second) >= 1
    assert transients.mean_per_second < 1.0
    assert transients.peak_per_second >= transients.mean_per_second


def test_analysis_is_byte_identical_across_runs(recording: SyntheticRecording) -> None:
    first = run_analysis(recording.path).model_dump_json(indent=2)
    second = run_analysis(recording.path).model_dump_json(indent=2)
    assert first == second


def test_timings_are_opt_in(recording: SyntheticRecording) -> None:
    without = run_analysis(recording.path, analyzers=["peaks"])
    with_timings = run_analysis(recording.path, analyzers=["peaks"], timings=True)
    assert without.analyzers[0].duration_ms is None
    assert with_timings.analyzers[0].duration_ms is not None


def test_subset_selection_pulls_in_dependencies(recording: SyntheticRecording) -> None:
    document = run_analysis(recording.path, analyzers=["boundaries"])
    ran = [run.name for run in document.analyzers]
    assert ran == ["rms_profile", "surface_noise", "silence", "boundaries"]
    assert document.clicks is None
    assert document.boundaries is not None


def test_config_overrides_reach_the_analyzer_and_are_recorded(
    recording: SyntheticRecording,
) -> None:
    config = Config(analyzer={"rms_profile": {"hop_seconds": 0.05}})
    document = run_analysis(recording.path, analyzers=["rms_profile"], config=config)
    assert document.rms_profile is not None
    assert document.rms_profile.hop_seconds == 0.05
    assert document.rms_profile.meta.params["hop_seconds"] == 0.05
    assert document.config_digest == config.digest()


def test_unknown_analyzer_parameter_fails_that_analyzer_only(
    recording: SyntheticRecording,
) -> None:
    config = Config(analyzer={"rms_profile": {"windwo_seconds": 0.2}})
    document = run_analysis(recording.path, analyzers=["rms_profile", "peaks"], config=config)
    statuses = {run.name: run.status for run in document.analyzers}
    assert statuses["rms_profile"] == "failed"
    assert statuses["peaks"] == "ok"
    assert document.rms_profile is None
    assert document.peaks is not None


def test_a_failing_analyzer_degrades_the_document_instead_of_the_run(
    recording: SyntheticRecording, monkeypatch: pytest.MonkeyPatch
) -> None:
    all_analyzers()  # force built-in registration

    def explode(_context: AnalyzerContext) -> Section:
        raise RuntimeError("synthetic failure")

    broken = dataclasses.replace(registry_module._ANALYZERS["rms_profile"], fn=explode)
    monkeypatch.setitem(registry_module._ANALYZERS, "rms_profile", broken)

    document = run_analysis(recording.path, analyzers=["silence", "peaks"])
    statuses = {run.name: run.status for run in document.analyzers}
    assert statuses["rms_profile"] == "failed"
    assert statuses["surface_noise"] == "skipped"
    assert statuses["silence"] == "skipped"
    assert statuses["peaks"] == "ok"
    assert any("synthetic failure" in warning for warning in document.warnings)


def test_unknown_analyzer_name_is_rejected(recording: SyntheticRecording) -> None:
    with pytest.raises(AnalysisError, match="unknown analyzer"):
        run_analysis(recording.path, analyzers=["nope"])

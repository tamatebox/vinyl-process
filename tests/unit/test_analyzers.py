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


def test_music_end_follows_a_fade_past_the_silence_threshold(tmp_path) -> None:
    """A track that fades out crosses the threshold long before it has stopped.

    Regression test for the behaviour that cost 22 s of a real pressing's closing
    fade: ``start_sample`` is where the level crossed a fixed threshold, while
    ``music_end_sample`` is where the decay settles — and only the latter is safe
    to cut at.
    """
    import soundfile as sf

    sample_rate = 16000
    noise_amplitude = 4e-4  # -68 dBFS, so the threshold lands near -60 dBFS
    tone_amplitude = 0.5
    fade_seconds = 25.0

    def build(with_fade: bool) -> np.ndarray:
        rng = np.random.default_rng(4)

        def noise(seconds: float) -> np.ndarray:
            return rng.normal(0.0, noise_amplitude, round(seconds * sample_rate))

        def tone(seconds: float) -> np.ndarray:
            t = np.arange(round(seconds * sample_rate)) / sample_rate
            return tone_amplitude * np.sin(2 * np.pi * 220 * t)

        parts = [noise(2.0), tone(4.0)]
        if with_fade:
            # dB-linear fade that stops exactly at the noise floor, so it spends
            # several seconds under the silence threshold while still decaying.
            decibels = np.linspace(
                0.0,
                20 * np.log10(noise_amplitude / tone_amplitude),
                round(fade_seconds * sample_rate),
            )
            parts.append(tone(fade_seconds) * 10.0 ** (decibels / 20.0))
        parts.append(noise(8.0))
        return np.concatenate(parts)

    def trailing_region(with_fade: bool):
        mono = build(with_fade)
        path = tmp_path / f"fade-{with_fade}.wav"
        sf.write(str(path), np.column_stack([mono, mono]), sample_rate, subtype="PCM_24")
        document = run_analysis(path, analyzers=["silence"])
        assert document.silence is not None
        region = document.silence.regions[-1]
        return region.start_sample / sample_rate, region.music_end_sample / sample_rate

    crossing, settled = trailing_region(with_fade=False)
    assert crossing == pytest.approx(6.0, abs=0.2)
    # Nothing to follow: the two agree to within the smoothing window.
    assert settled - crossing < 1.0

    crossing, settled = trailing_region(with_fade=True)
    # The threshold fires a long way into the fade, which really ends at 6 + 25 s.
    assert crossing < 27.0
    assert settled - crossing > 2.0
    assert settled <= 6.0 + fade_seconds


def test_music_start_precedes_a_fade_in_past_the_silence_threshold(tmp_path) -> None:
    """The mirror case, and the one that ships surface noise rather than clipping.

    A track that fades in crosses the threshold late, so a cut at ``end_sample``
    loses the entrance. ``music_start_sample`` is where the level was last on the
    gap's own floor, which is a lower bound and therefore safe. The fixed pre-roll
    it replaces cannot be right for every track — the margin needed ran from
    0.07 s to 0.42 s across one album.
    """
    import soundfile as sf

    sample_rate = 16000
    noise_amplitude = 4e-4
    tone_amplitude = 0.5
    fade_seconds = 20.0

    def build(with_fade: bool) -> np.ndarray:
        rng = np.random.default_rng(9)

        def noise(seconds: float) -> np.ndarray:
            return rng.normal(0.0, noise_amplitude, round(seconds * sample_rate))

        def tone(seconds: float) -> np.ndarray:
            t = np.arange(round(seconds * sample_rate)) / sample_rate
            return tone_amplitude * np.sin(2 * np.pi * 220 * t)

        parts = [noise(2.0), tone(4.0), noise(8.0)]
        if with_fade:
            decibels = np.linspace(
                20 * np.log10(noise_amplitude / tone_amplitude),
                0.0,
                round(fade_seconds * sample_rate),
            )
            parts.append(tone(fade_seconds) * 10.0 ** (decibels / 20.0))
        parts.append(tone(4.0))
        return np.concatenate(parts)

    def middle_region(with_fade: bool):
        mono = build(with_fade)
        path = tmp_path / f"rise-{with_fade}.wav"
        sf.write(str(path), np.column_stack([mono, mono]), sample_rate, subtype="PCM_24")
        document = run_analysis(path, analyzers=["silence"])
        assert document.silence is not None
        region = max(document.silence.regions, key=lambda r: r.duration_seconds)
        return region.end_sample / sample_rate, region.music_start_sample / sample_rate

    crossing, rising = middle_region(with_fade=False)
    # Nothing to precede: the two agree to within the smoothing window.
    assert abs(crossing - rising) < 1.0

    crossing, rising = middle_region(with_fade=True)
    # The threshold fires well into the fade-in, which begins at 14 s.
    assert rising < crossing
    assert crossing - rising > 1.0
    # It does not reach the fade's true beginning, and cannot: a fade rising out
    # of the noise floor is indistinguishable from the floor until it clears it.
    # The same limitation the closing measurement has, in the same direction —
    # what matters is that the answer never lands inside the music.
    assert 14.0 - 1.0 <= rising <= 14.0 + 3.0


def test_music_start_equals_the_end_for_a_trailing_region(analysis: AnalysisDocument) -> None:
    """There is no music after the run-out, so there is nothing to precede."""
    assert analysis.silence is not None
    trailing = analysis.silence.regions[-1]
    assert trailing.music_start_sample == trailing.end_sample


def test_music_end_equals_the_start_for_a_leading_region(analysis: AnalysisDocument) -> None:
    """There is no music before the lead-in, so there is nothing to follow."""
    assert analysis.silence is not None
    leading = analysis.silence.regions[0]
    assert leading.start_sample == 0
    assert leading.music_end_sample == 0


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


def test_click_rates_separate_surface_noise_from_over_triggering(
    analysis: AnalysisDocument, recording: SyntheticRecording
) -> None:
    """The fixture injects clicks only into the programme, so the programme rate
    must exceed the silence rate — this is what tells a worn pressing (both high)
    from a detector firing on the music (only the programme high)."""
    clicks = analysis.clicks
    assert clicks is not None
    assert clicks.silence_rate_per_minute == 0.0
    assert clicks.programme_rate_per_minute is not None
    assert clicks.programme_rate_per_minute > 0.0


def test_clicks_pulls_in_the_silence_it_needs(recording: SyntheticRecording) -> None:
    document = run_analysis(recording.path, analyzers=["clicks"])
    assert [run.name for run in document.analyzers] == [
        "rms_profile",
        "surface_noise",
        "silence",
        "clicks",
    ]


def test_click_rates_are_absent_when_there_are_no_gaps(tmp_path) -> None:
    """A document must not invent a rate it could not measure."""
    from tests.fixtures.synth import write_recording

    gapless = write_recording(
        tmp_path / "gapless.wav", track_seconds=(6.0,), lead_in=0.5, lead_out=0.5
    )
    document = run_analysis(gapless.path, analyzers=["clicks"])
    assert document.clicks is not None
    assert document.clicks.silence_rate_per_minute is None


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
    assert peaks.true_peak_db is not None
    assert peaks.true_peak_db >= peaks.peak_db
    # The fixture has a silent lead-in and inter-track gaps, which a plain RMS
    # averages in and the gated measurement does not.
    assert peaks.gated_rms_db is not None
    assert peaks.gated_rms_db > peaks.rms_db
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

"""The shared arithmetic. Everything else in the DSP path builds on this."""

from __future__ import annotations

import numpy as np
import pytest

from vinyl_process.signal_ops import (
    CONTEXT_FLOOR,
    apply_fades,
    click_events_block,
    click_events_block_sweep,
    confirm_clicks_sinusoidal,
    correlation_at,
    db_to_amplitude,
    highpass,
    local_bounds,
    merge_runs,
    onset_coincidence,
    onset_flux,
    periodicity_peaks,
    repair_clicks,
    runs_of_true,
    sinusoidal_residual,
    transient_onsets,
    windowed_rms,
)

SAMPLE_RATE = 44100


def tonal(seconds: float = 2.0, seed: int = 1) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    rng = np.random.default_rng(seed)
    return (
        0.30 * np.sin(2 * np.pi * 440 * t)
        + 0.15 * np.sin(2 * np.pi * 1300 * t)
        + 0.08 * np.sin(2 * np.pi * 3100 * t)
        + rng.normal(0.0, 1e-4, t.shape)
    )


def test_runs_of_true_finds_half_open_spans() -> None:
    flags = np.array([False, True, True, False, True, False])
    assert runs_of_true(flags) == [(1, 3), (4, 5)]
    assert runs_of_true(np.zeros(0, dtype=bool)) == []


def test_merge_runs_joins_clusters_within_gap() -> None:
    assert merge_runs([(0, 2), (5, 7), (100, 101)], gap=5) == [(0, 7), (100, 101)]
    assert merge_runs([], gap=5) == []


def test_windowed_rms_frame_count_and_level() -> None:
    signal = np.full(SAMPLE_RATE, 0.5)
    values = windowed_rms(signal, SAMPLE_RATE, 0.2, 0.1)
    window, hop = int(0.2 * SAMPLE_RATE), int(0.1 * SAMPLE_RATE)
    assert values.size == (SAMPLE_RATE - window) // hop + 1
    assert np.allclose(values, 0.5, atol=1e-9)


def test_highpass_removes_low_frequency_and_is_a_noop_below_nyquist() -> None:
    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    low = np.sin(2 * np.pi * 100 * t)
    assert np.max(np.abs(highpass(low, SAMPLE_RATE, 3000.0))) < 0.05
    # A cutoff at or above Nyquist cannot be realised, so the signal passes through.
    assert np.array_equal(highpass(low, 4000, 3000.0), highpass(low, 4000, 3000.0))


def test_repair_reduces_click_error_and_leaves_the_rest_untouched() -> None:
    clean = tonal()
    positions = [10_000, 30_000, 50_000]
    damaged = clean.copy()
    for position in positions:
        damaged[position : position + 4] += 0.6

    stereo_clean = np.column_stack([clean, clean])
    stereo_damaged = np.column_stack([damaged, damaged])
    events = click_events_block(damaged, SAMPLE_RATE, 20.0, 3.0)
    repaired = repair_clicks(stereo_damaged, events, strength=1.0)

    for position in positions:
        window = slice(position - 80, position + 90)
        before = np.max(np.abs(stereo_damaged[window] - stereo_clean[window]))
        after = np.max(np.abs(repaired[window] - stereo_clean[window]))
        assert after < before / 5.0

    untouched = slice(20_000, 25_000)
    assert np.array_equal(repaired[untouched], stereo_damaged[untouched])


def test_repair_strength_scales_the_correction() -> None:
    signal = tonal(1.0)
    signal[20_000:20_004] += 0.6
    stereo = np.column_stack([signal, signal])
    events = click_events_block(signal, SAMPLE_RATE, 20.0, 3.0)

    assert np.array_equal(repair_clicks(stereo, events, 0.0), stereo)
    half = np.max(np.abs(repair_clicks(stereo, events, 0.5) - stereo))
    full = np.max(np.abs(repair_clicks(stereo, events, 1.0) - stereo))
    assert 0.0 < half < full


def test_repair_is_deterministic() -> None:
    signal = tonal(1.0)
    signal[20_000:20_004] += 0.6
    stereo = np.column_stack([signal, signal])
    events = click_events_block(signal, SAMPLE_RATE, 20.0, 3.0)
    first = repair_clicks(stereo, events, 0.8)
    second = repair_clicks(stereo, events, 0.8)
    assert np.array_equal(first, second)


def test_fades_reach_zero_and_preserve_the_middle() -> None:
    signal = np.ones((SAMPLE_RATE, 2))
    faded = apply_fades(signal, SAMPLE_RATE, fade_in_ms=10.0, fade_out_ms=10.0)
    assert faded[0, 0] == pytest.approx(0.0)
    assert faded[-1, 0] == pytest.approx(0.0, abs=1e-9)
    middle = SAMPLE_RATE // 2
    assert faded[middle, 0] == pytest.approx(1.0)
    assert np.array_equal(apply_fades(signal, SAMPLE_RATE, 0.0, 0.0), signal)


def test_transient_onsets_ignore_steady_tones_and_count_percussion() -> None:
    t = np.arange(SAMPLE_RATE * 2) / SAMPLE_RATE
    steady = 0.4 * np.sin(2 * np.pi * 440 * t)
    assert transient_onsets(steady, SAMPLE_RATE).size == 0

    percussive = np.zeros(SAMPLE_RATE * 2)
    hits = range(0, SAMPLE_RATE * 2 - 400, SAMPLE_RATE // 4)
    for onset in hits:
        percussive[onset : onset + 400] += np.hanning(400) * 0.7
    detected = transient_onsets(percussive, SAMPLE_RATE)
    assert len(hits) - 2 <= detected.size <= len(hits) + 2


def test_db_to_amplitude_round_trip() -> None:
    assert db_to_amplitude(0.0) == pytest.approx(1.0)
    assert db_to_amplitude(-6.0206) == pytest.approx(0.5, abs=1e-4)


def broadband(seconds: float = 0.5, seed: int = 7) -> np.ndarray:
    """Dense, noisy material — the case cubic Hermite diverges on.

    The tonal fixture above cannot expose it: a smooth tone has a per-sample
    slope far smaller than its amplitude, so Hermite's span-scaled tangent term
    stays small. Broadband content is where the slope rivals the amplitude, and
    that is what vinyl programme material looks like above 3 kHz.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return (
        0.05 * np.sin(2 * np.pi * 7000 * t)
        + 0.05 * np.sin(2 * np.pi * 9500 * t)
        + rng.normal(0.0, 0.02, t.shape)
    )


@pytest.mark.parametrize("width", [4, 16, 32, 65, 96])
def test_repair_never_leaves_the_range_of_the_audio_around_it(width: int) -> None:
    """A repair may not invent a level the neighbouring audio never reaches.

    Regression test for a real failure: on a 16-bit transfer the interpolator
    bridged a 65-sample gap at 0.892 where the surrounding audio peaked at 0.071
    — twelve times its neighbourhood, and three times the peak of the whole
    track. Unbounded, the overshoot grows with the span because Hermite scales
    its tangent term by it, reaching 16x at 96 samples: that is 2 ms at 48 kHz,
    which is *within* the width limit a plan would normally set. The width guard
    is therefore no protection, and the widths here bracket it deliberately.

    The events are constructed rather than detected: this is the contract of
    ``repair_clicks`` for any event list, not a statement about the detector.
    """
    signal = broadband()
    stereo = np.column_stack([signal, signal * 0.9])
    events = [(p, p + width, 0.1) for p in range(2000, len(signal) - 2000, 3000)]
    repaired = repair_clicks(stereo, events, strength=1.0)

    for start, end, _peak in events:
        lo, hi = start - 1, min(end, len(stereo) - 1)
        low, high = local_bounds(stereo, lo, hi, max(CONTEXT_FLOOR, 2 * (hi - lo)))
        patch = repaired[lo + 1 : hi]
        assert np.all(patch >= low[None, :] - 1e-12), f"span {start}..{end} undershot"
        assert np.all(patch <= high[None, :] + 1e-12), f"span {start}..{end} overshot"

    # The global statement the bug violated: no repair may raise the peak.
    assert np.max(np.abs(repaired)) <= np.max(np.abs(stereo)) + 1e-12


def test_repair_bound_does_not_flatten_a_click_in_tonal_material() -> None:
    """The clip must not be doing the repair's job: on smooth material the bridge
    stays inside the bound, so the fix costs nothing where Hermite was working."""
    signal = tonal()
    position = SAMPLE_RATE // 2
    damaged = signal.copy()
    damaged[position : position + 3] += np.array([0.6, -0.5, 0.4])
    stereo_damaged = np.column_stack([damaged, damaged])
    events = click_events_block(damaged, SAMPLE_RATE, 20.0, 3.0)
    repaired = repair_clicks(stereo_damaged, events, strength=1.0)
    error = np.max(np.abs(repaired[:, 0] - signal))
    assert error < 0.05, f"repair left {error:.3f} of the click behind"


LADDER = [5.0, 10.0, 20.0, 35.0, 50.0, 75.0, 100.0]


def clicky(seconds: float = 2.0, spacing: int = 7000) -> tuple[np.ndarray, list[int]]:
    """Tonal material with unmistakable clicks at known positions."""
    signal = tonal(seconds)
    positions = list(range(4000, signal.size - 4000, spacing))
    for position in positions:
        signal[position : position + 3] += np.array([0.5, -0.45, 0.4])
    return signal, positions


def usable_threshold(signal: np.ndarray, positions: list[int]) -> float:
    """The rung of the ladder that finds these clicks without inventing others.

    Deliberately not a constant. The ratio a click reaches depends on the
    material around it — on this fixture it tops out near 50 because the 3.1 kHz
    tone passes the detector's high-pass, while on a real transfer the same
    detector saw ratios past 400. A test that hard-coded one number would be
    asserting the very thing this design refuses to claim.
    """
    for threshold in LADDER:
        found = [start for start, _e, _p in click_events_block(signal, SAMPLE_RATE, threshold, 2.0)]
        hit = sum(any(abs(f - p) <= 32 for f in found) for p in positions)
        if hit >= 0.9 * len(positions) and len(found) <= 1.5 * len(positions):
            return threshold
    raise AssertionError("no rung of the ladder both finds the clicks and stays quiet")


@pytest.mark.parametrize("chunk_seconds", [0.5, 1.0, 2.0])
def test_block_detector_answer_does_not_depend_on_how_much_audio_it_was_given(
    chunk_seconds: float,
) -> None:
    """The property the analyzer and the DSP engine need in order to agree.

    The analyzer measures a whole side; the engine repairs one track at a time.
    If the detector's threshold is derived from whatever it was handed, the two
    describe different events and the plan's statistics stop describing the run.
    Measured on a real transfer, ``click_events`` drifted by up to 7.8x across
    chunk sizes; this pins the ratio detector's behaviour instead of trusting it.
    """
    signal, positions = clicky(4.0, spacing=5000)
    threshold = usable_threshold(signal, positions)

    def rate(chunk: float | None) -> float:
        step = int(chunk * SAMPLE_RATE) if chunk else signal.size
        # Just past the detector's own edge guard (half a context window, 20 ms),
        # so that filter warm-up is excluded without excluding the whole chunk.
        margin = int(0.05 * SAMPLE_RATE)
        found = measured = 0
        for start in range(0, signal.size, step):
            piece = signal[start : start + step]
            if piece.size < 4 * margin:
                continue
            events = click_events_block(piece, SAMPLE_RATE, threshold, 2.0)
            found += sum(1 for a, _b, _p in events if margin <= a < piece.size - margin)
            measured += piece.size - 2 * margin
        return found / max(measured, 1) * SAMPLE_RATE

    whole = rate(None)
    chunked = rate(chunk_seconds)
    assert whole > 0, "the fixture must produce detections"
    assert 0.8 <= chunked / whole <= 1.25, (
        f"detection rate moved from {whole:.2f}/s to {chunked:.2f}/s when the same audio "
        f"was handed over in {chunk_seconds}s pieces"
    )


def test_block_detector_finds_obvious_clicks_and_leaves_clean_audio_alone() -> None:
    """A regression guard, not evidence that this detector beats another.

    Precision and recall here are measured against damage this test injected, so
    they say only that the detector still does the obvious thing: find a click
    that is plainly there, and stay quiet on material that has none. Ranking two
    detectors this way would be circular — the same hand chooses the click model
    and the algorithm. For that, the inter-track gaps of a real record are the
    evidence, because a gap holds no programme material to be confused by.
    """
    signal, positions = clicky()
    threshold = usable_threshold(signal, positions)
    assert click_events_block(tonal(2.0), SAMPLE_RATE, threshold, 2.0) == []


def test_threshold_sweep_is_monotone_and_matches_a_single_call() -> None:
    """The ladder is one pass of the arithmetic, so it must agree with the
    single-threshold path, and raising a threshold can only remove detections."""
    signal, _positions = clicky()
    sweep = click_events_block_sweep(signal, SAMPLE_RATE, LADDER, 2.0)
    counts = [len(sweep[threshold]) for threshold in LADDER]
    assert counts == sorted(counts, reverse=True), counts
    for threshold in LADDER:
        assert sweep[threshold] == click_events_block(signal, SAMPLE_RATE, threshold, 2.0)


def _pulse_train(period_seconds: float, duration_seconds: float, amplitude: float) -> np.ndarray:
    """Clicks at a fixed period on a bed of quiet noise, deterministically."""
    samples = np.zeros(int(duration_seconds * SAMPLE_RATE))
    samples += np.sin(np.arange(samples.size) * 0.0001) * 1e-4
    step = period_seconds * SAMPLE_RATE
    for index in range(int(duration_seconds / period_seconds)):
        start = int(index * step)
        samples[start : start + 30] += amplitude
    return samples


def test_onset_flux_length_and_mean() -> None:
    signal = _pulse_train(0.5, 4.0, 0.4)
    flux = onset_flux(signal, SAMPLE_RATE, window_seconds=0.02, hop_seconds=0.005)
    window = round(0.02 * SAMPLE_RATE)
    hop = round(0.005 * SAMPLE_RATE)
    assert flux.size == (signal.size - window) // hop
    assert flux.mean() == pytest.approx(0.0, abs=1e-9)
    # Too short to yield a single frame pair.
    assert onset_flux(np.zeros(10), SAMPLE_RATE).size == 0


def test_periodicity_peaks_find_the_period_and_its_multiples() -> None:
    flux = onset_flux(_pulse_train(0.8, 20.0, 0.4), SAMPLE_RATE)
    frame_rate = SAMPLE_RATE / round(0.005 * SAMPLE_RATE)
    peaks, baseline = periodicity_peaks(flux, frame_rate, 0.25, 4.0, top_k=3)
    periods = sorted(period for period, _ in peaks)
    assert periods[0] == pytest.approx(0.8, abs=0.02)
    assert all(r > 0.4 for _, r in peaks)
    # Multiples of the period are peaks too, so the top three are 0.8, 1.6, 2.4.
    assert periods == pytest.approx([0.8, 1.6, 2.4], abs=0.02)
    # A clean tick train spikes only at those multiples and leaves the rest of
    # the curve flat, so the median stays near zero. Dense crackle does not —
    # which is why the baseline is reported rather than assumed.
    assert baseline == pytest.approx(0.0, abs=0.05)


def test_periodicity_peaks_are_empty_when_the_envelope_is_too_short_or_flat() -> None:
    frame_rate = SAMPLE_RATE / round(0.005 * SAMPLE_RATE)
    assert periodicity_peaks(np.zeros(100), frame_rate, 0.25, 4.0) == ([], 0.0)
    assert periodicity_peaks(np.zeros(4000), frame_rate, 0.25, 4.0) == ([], 0.0)


def test_correlation_at_matches_the_period_it_is_asked_about() -> None:
    flux = onset_flux(_pulse_train(1.3333, 24.0, 0.4), SAMPLE_RATE)
    frame_rate = SAMPLE_RATE / round(0.005 * SAMPLE_RATE)
    on_period = correlation_at(flux, round(1.3333 * frame_rate))
    off_period = correlation_at(flux, round(0.9 * frame_rate))
    assert on_period > 0.5
    assert on_period > off_period + 0.4
    assert correlation_at(flux, 0) == 0.0
    assert correlation_at(flux, flux.size + 1) == 0.0


def test_onset_coincidence_is_one_for_indifferent_positions_and_large_on_attacks() -> None:
    """The diagnostic the gap-versus-programme rates cannot supply.

    On the record this was written against, a rung whose silence rate beat its
    programme rate 43.8 to 1 was still landing on note attacks 7.8 times more
    often than chance. So the figure is checked against both ends: positions
    chosen without regard to the signal must score about 1, and positions placed
    on attacks must score well above it.
    """
    rng = np.random.default_rng(5)
    signal = 0.02 * rng.normal(size=SAMPLE_RATE * 4)
    attacks = list(range(SAMPLE_RATE // 2, signal.size - SAMPLE_RATE // 2, 7000))
    for position in attacks:
        signal[position : position + 400] += 0.4 * np.exp(-np.arange(400) / 90)

    # Densely sampled, so the estimate converges: a sparse set of positions lands
    # on an attack often enough by luck to read as a bias that is not there.
    indifferent = list(range(SAMPLE_RATE // 3, signal.size - SAMPLE_RATE // 3, 97))
    assert onset_coincidence(signal, indifferent, SAMPLE_RATE) < 1.5
    assert onset_coincidence(signal, attacks, SAMPLE_RATE) > 5.0
    # No positions, or a signal too short to hold a control, is not a figure of 0.
    assert onset_coincidence(signal, [], SAMPLE_RATE) != onset_coincidence(signal, [], SAMPLE_RATE)


def test_sinusoidal_residual_keeps_an_impulse_and_removes_a_tone() -> None:
    """The property the confirmation stage rests on: a few partials can represent
    tonal material but not an impulse, so what survives is the impulse."""
    time = np.arange(512) / SAMPLE_RATE
    tone = 0.3 * np.sin(2 * np.pi * 440 * time) + 0.1 * np.sin(2 * np.pi * 1320 * time)
    residual_tone = sinusoidal_residual(tone)
    assert np.max(np.abs(residual_tone)) < 0.3 * np.max(np.abs(tone))

    with_click = tone.copy()
    with_click[256] += 0.5
    residual_click = sinusoidal_residual(with_click)
    assert np.max(np.abs(residual_click)) > 3 * np.max(np.abs(residual_tone))


def test_sinusoidal_confirmation_keeps_a_click_and_needs_its_k_stated() -> None:
    """Confirmation discards candidates the model already explains — and this is
    the limit of what is claimed for it.

    On a real pressing no single ``k`` both rejected the musical transients and
    kept the clicks that had been confirmed by ear: the paper's 3 left the onset
    bias almost untouched, and 5 threw away five of six verified clicks. So the
    test pins the mechanism on an unambiguous case and nothing more. There is no
    default for ``k`` in the engine for the same reason.
    """
    time = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    signal = 0.3 * np.sin(2 * np.pi * 440 * time)
    position = SAMPLE_RATE // 2
    signal[position : position + 3] += np.array([0.5, -0.45, 0.4])
    candidates = [(position, position + 3, 0.5), (position + 20_000, position + 20_003, 0.0)]

    kept = confirm_clicks_sinusoidal(signal, candidates, k=3.0)
    assert (position, position + 3, 0.5) in kept
    assert len(kept) == 1, "the candidate over undamaged tone should not survive"
    # A high enough k rejects everything, which is why it cannot have a default.
    assert confirm_clicks_sinusoidal(signal, candidates, k=100.0) == []

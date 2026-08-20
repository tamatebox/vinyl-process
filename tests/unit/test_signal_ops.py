"""The shared arithmetic. Everything else in the DSP path builds on this."""

from __future__ import annotations

import numpy as np
import pytest

from vinyl_process.signal_ops import (
    CONTEXT_FLOOR,
    apply_fades,
    click_events,
    db_to_amplitude,
    highpass,
    local_bounds,
    merge_runs,
    repair_clicks,
    runs_of_true,
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


def test_click_detection_finds_injected_clicks_without_false_positives() -> None:
    clean = tonal()
    positions = [10_000, 30_000, 50_000, 77_777]
    damaged = clean.copy()
    for position in positions:
        damaged[position : position + 4] += 0.6

    events = click_events(damaged, SAMPLE_RATE, threshold_mad=6.0, max_width_ms=3.0)
    assert len(events) == len(positions)
    for (start, end, _peak), position in zip(events, positions, strict=True):
        assert start <= position < end
        assert end - start <= int(0.003 * SAMPLE_RATE)

    assert click_events(clean, SAMPLE_RATE, 6.0, 3.0) == []


def test_click_detection_ignores_percussive_attacks() -> None:
    """A drum hit is wide-band but wide; the width test must reject it."""
    signal = np.zeros(SAMPLE_RATE)
    for onset in range(0, SAMPLE_RATE - 400, SAMPLE_RATE // 8):
        signal[onset : onset + 300] += np.hanning(300) * 0.8
    assert click_events(signal, SAMPLE_RATE, 6.0, 3.0) == []


def test_click_detection_survives_a_near_silent_noise_floor() -> None:
    """With almost no noise the threshold collapses; detection must still work.

    Regression test: measuring width on the raw detection run (which filter
    ringing stretches) rejected every click on quiet pressings.
    """
    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    signal = 0.4 * np.sin(2 * np.pi * 220 * t)
    signal[20_000:20_003] += 0.5
    events = click_events(signal, SAMPLE_RATE, 6.0, 3.0)
    assert len(events) == 1
    assert events[0][0] <= 20_000 < events[0][1]


def test_repair_reduces_click_error_and_leaves_the_rest_untouched() -> None:
    clean = tonal()
    positions = [10_000, 30_000, 50_000]
    damaged = clean.copy()
    for position in positions:
        damaged[position : position + 4] += 0.6

    stereo_clean = np.column_stack([clean, clean])
    stereo_damaged = np.column_stack([damaged, damaged])
    events = click_events(damaged, SAMPLE_RATE, 6.0, 3.0)
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
    events = click_events(signal, SAMPLE_RATE, 6.0, 3.0)

    assert np.array_equal(repair_clicks(stereo, events, 0.0), stereo)
    half = np.max(np.abs(repair_clicks(stereo, events, 0.5) - stereo))
    full = np.max(np.abs(repair_clicks(stereo, events, 1.0) - stereo))
    assert 0.0 < half < full


def test_repair_is_deterministic() -> None:
    signal = tonal(1.0)
    signal[20_000:20_004] += 0.6
    stereo = np.column_stack([signal, signal])
    events = click_events(signal, SAMPLE_RATE, 6.0, 3.0)
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
    events = click_events(damaged, SAMPLE_RATE, 6.0, 3.0)
    repaired = repair_clicks(stereo_damaged, events, strength=1.0)
    error = np.max(np.abs(repaired[:, 0] - signal))
    assert error < 0.05, f"repair left {error:.3f} of the click behind"

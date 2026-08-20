"""Pure numeric helpers shared by the analyzer and the DSP engines.

This module knows nothing about contracts or decisions. It exists so that the
analyzer's click *detection* and the native engine's click *repair* use exactly
the same arithmetic without the two layers importing each other — the one
mechanism that keeps "measure" and "execute" independent yet consistent.

Every function here is deterministic: no randomness, no wall clock.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from scipy.ndimage import median_filter
from scipy.signal import butter, sosfiltfilt

EPS = 1e-12
"""Floor for log/division so silence yields -240 dB instead of -inf."""

ClickEvent = tuple[int, int, float]
"""``(start_sample, end_sample, peak_residual_amplitude)``, end exclusive."""


def amplitude_to_db(x: npt.ArrayLike) -> npt.NDArray[np.float64]:
    """Linear amplitude to dBFS. Scalars come back as 0-d arrays, so ``float()``
    and ``np.asarray()`` both work on the result."""
    return np.asarray(20.0 * np.log10(np.maximum(np.abs(x), EPS)), dtype=np.float64)


def db_to_amplitude(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def windowed_rms(
    mono: np.ndarray, sample_rate: int, window_seconds: float, hop_seconds: float
) -> npt.NDArray[np.float64]:
    """RMS per window (linear amplitude), hop-aligned to sample 0.

    Frame ``i`` covers ``[i*hop, i*hop + window)``; only whole windows are
    emitted, so ``frame_count = (n - window) // hop + 1``.
    """
    window = max(1, round(window_seconds * sample_rate))
    hop = max(1, round(hop_seconds * sample_rate))
    if len(mono) < window:
        return np.array([np.sqrt(np.mean(mono**2) + EPS)]) if len(mono) else np.zeros(0)
    cumulative = np.concatenate([[0.0], np.cumsum(np.asarray(mono, dtype=np.float64) ** 2)])
    starts = np.arange(0, len(mono) - window + 1, hop)
    sums = cumulative[starts + window] - cumulative[starts]
    return np.asarray(np.sqrt(sums / window + EPS), dtype=np.float64)


def runs_of_true(flags: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous ``True`` runs of a boolean array as ``[start, end)`` pairs."""
    if flags.size == 0:
        return []
    edges = np.flatnonzero(np.diff(np.concatenate([[0], flags.astype(np.int8), [0]])))
    return [(int(s), int(e)) for s, e in zip(edges[::2], edges[1::2], strict=True)]


def highpass(mono: np.ndarray, sample_rate: int, cutoff_hz: float, order: int = 4) -> np.ndarray:
    """Zero-phase Butterworth high-pass. Returns the input unchanged if the
    cutoff is not below Nyquist (very low sample rates)."""
    nyquist = sample_rate / 2.0
    if cutoff_hz <= 0 or cutoff_hz >= nyquist * 0.98 or mono.size < 3 * order:
        return np.asarray(mono, dtype=np.float64)
    sos = butter(order, cutoff_hz / nyquist, btype="highpass", output="sos")
    return np.asarray(sosfiltfilt(sos, mono), dtype=np.float64)


def merge_runs(runs: list[tuple[int, int]], gap: int) -> list[tuple[int, int]]:
    """Merge ``[start, end)`` runs separated by fewer than ``gap`` samples.

    A single physical click survives high-pass filtering as a small cluster of
    threshold crossings (zero-phase filters ring symmetrically). Without merging,
    one click would be counted several times *and* the repair would interpolate
    around the impulse instead of across it.
    """
    if not runs:
        return []
    merged = [runs[0]]
    for start, end in runs[1:]:
        last_start, last_end = merged[-1]
        if start - last_end < gap:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def click_events(
    mono: np.ndarray,
    sample_rate: int,
    threshold_mad: float,
    max_width_ms: float,
    highpass_hz: float = 3000.0,
) -> list[ClickEvent]:
    """Detect impulsive clicks.

    Two stages, because either alone gives false positives on real music:

    1. high-pass at ``highpass_hz`` — vinyl clicks are broadband impulses while
       programme material is concentrated lower, so this suppresses the music
       without suppressing the damage;
    2. subtract a median-filtered copy (kernel scaled to ``max_width_ms``) to
       remove *sustained* high-frequency content (hiss, cymbals), leaving
       transient spikes.

    Samples whose residual exceeds ``threshold_mad`` robust sigmas are click
    samples; runs wider than ``max_width_ms`` are programme material, not damage.
    """
    if mono.size == 0:
        return []
    max_width = max(1, round(max_width_ms / 1000.0 * sample_rate))
    detection = highpass(mono, sample_rate, highpass_hz)
    kernel = max(3, (2 * max_width + 1) | 1)
    residual = detection - median_filter(detection, size=kernel, mode="nearest")
    # The filters are unreliable within one kernel of each edge (padding, not
    # signal), so that region is declared undetectable rather than reported.
    guard = min(kernel, residual.size // 2)
    if guard:
        residual[:guard] = 0.0
        residual[-guard:] = 0.0
    sigma = 1.4826 * float(np.median(np.abs(residual - np.median(residual))))
    if sigma < EPS:
        return []
    hot = np.abs(residual) > threshold_mad * sigma
    curvature = second_difference(mono)
    curvature_sigma = 1.4826 * float(np.median(np.abs(curvature - np.median(curvature))))
    events: list[ClickEvent] = []
    for start, end in merge_runs(runs_of_true(hot), gap=max_width):
        peak = float(np.max(np.abs(residual[start:end])))
        span_start, span_end = _localise(
            curvature, start, end, threshold_mad * curvature_sigma, max_width
        )
        # The width test belongs on the *localised* span, which is the physical
        # extent of the damage. The detection run is not a width measurement: on
        # a quiet pressing the threshold sits so low that filter ringing stretches
        # the run far past the impulse, and testing that would reject every click.
        if span_end - span_start > max_width:
            continue
        events.append((span_start, span_end, peak))
    return events


def second_difference(mono: np.ndarray) -> np.ndarray:
    """Centre-aligned second difference — a curvature estimate that is small for
    tonal material and huge at the step edges of a click."""
    out = np.zeros_like(mono, dtype=np.float64)
    if mono.size >= 3:
        out[1:-1] = mono[2:] - 2.0 * mono[1:-1] + mono[:-2]
    return out


def _localise(
    curvature: np.ndarray,
    start: int,
    end: int,
    threshold: float,
    max_width: int,
    pad: int = 2,
) -> tuple[int, int]:
    """Snap a detection span onto the impulse it actually found.

    Detection runs on a zero-phase-filtered signal, so a 4-sample click surfaces
    as a ~2 ms cluster that is neither centred on nor fully covering the damage.
    Interpolating that whole cluster would replace cycles of music with a bridge;
    missing its trailing edge would leave half the click in place. The curvature
    of the *unfiltered* signal localises the impulse to a few samples, searched
    in a window wide enough to correct either error.
    """
    n = curvature.size
    if threshold <= 0 or n == 0:
        return start, end
    search_start = max(0, start - max_width)
    search_end = min(n, end + max_width)
    hot = np.abs(curvature[search_start:search_end]) > threshold
    runs = merge_runs(runs_of_true(hot), gap=2 * pad + 1)
    if not runs:
        return start, end

    centre = (start + end) / 2.0 - search_start

    def distance(run: tuple[int, int]) -> float:
        run_start, run_end = run
        if run_start <= centre < run_end:
            return 0.0
        return min(abs(run_start - centre), abs(run_end - centre))

    hit_start, hit_end = min(runs, key=distance)
    lo = max(0, search_start + hit_start - pad)
    hi = min(n, search_start + hit_end + pad)
    return lo, hi


def repair_clicks(samples: np.ndarray, events: list[ClickEvent], strength: float) -> np.ndarray:
    """Bridge each click with cubic Hermite interpolation, blended by ``strength``.

    ``samples`` is ``(num_frames, num_channels)``; a repaired copy is returned.
    All channels are repaired over the same time window so stereo imaging is
    preserved.

    The endpoints are the last good sample before the click and the first good
    sample after it, with the tangents estimated from second-order one-sided
    differences of the surrounding good samples. Endpoint *values* must be the
    real samples, not a local average: averaging a few samples of an oscillating
    signal collapses towards its mean and offsets the whole bridge.
    """
    out = np.array(samples, dtype=np.float64, copy=True)
    n = out.shape[0]
    if n == 0 or strength <= 0.0:
        return out
    for start, end, _peak in events:
        lo = start - 1
        hi = min(end, n - 1)
        gap = hi - lo - 1
        if lo < 0 or gap <= 0:
            continue
        span = gap + 1
        y0, y1 = out[lo], out[hi]
        m0 = _slope_before(out, lo)
        m1 = _slope_after(out, hi)
        t = (np.arange(1, gap + 1, dtype=np.float64) / span)[:, None]
        t2, t3 = t * t, t * t * t
        patch = (
            (2.0 * t3 - 3.0 * t2 + 1.0) * y0[None, :]
            + (t3 - 2.0 * t2 + t) * (m0 * span)[None, :]
            + (-2.0 * t3 + 3.0 * t2) * y1[None, :]
            + (t3 - t2) * (m1 * span)[None, :]
        )
        out[lo + 1 : hi] = (1.0 - strength) * out[lo + 1 : hi] + strength * patch
    return out


def _slope_before(samples: np.ndarray, index: int) -> npt.NDArray[np.float64]:
    """Per-sample derivative at ``index`` from the good samples to its left."""
    if index >= 2:
        slope = (3.0 * samples[index] - 4.0 * samples[index - 1] + samples[index - 2]) / 2.0
    elif index >= 1:
        slope = samples[index] - samples[index - 1]
    else:
        slope = np.zeros(samples.shape[1], dtype=np.float64)
    return np.asarray(slope, dtype=np.float64)


def _slope_after(samples: np.ndarray, index: int) -> npt.NDArray[np.float64]:
    """Per-sample derivative at ``index`` from the good samples to its right."""
    n = samples.shape[0]
    if index + 2 < n:
        slope = (-3.0 * samples[index] + 4.0 * samples[index + 1] - samples[index + 2]) / 2.0
    elif index + 1 < n:
        slope = samples[index + 1] - samples[index]
    else:
        slope = np.zeros(samples.shape[1], dtype=np.float64)
    return np.asarray(slope, dtype=np.float64)


def apply_fades(
    samples: np.ndarray, sample_rate: int, fade_in_ms: float, fade_out_ms: float
) -> np.ndarray:
    """Raised-cosine fades at the edges of a cut, in place on a copy.

    Vinyl cuts land in surface noise, not true silence; a few milliseconds of
    fade removes the step discontinuity without audibly shortening the track.
    """
    if fade_in_ms <= 0 and fade_out_ms <= 0:
        return np.array(samples, dtype=np.float64, copy=True)
    out = np.array(samples, dtype=np.float64, copy=True)
    n = out.shape[0]
    fade_in = min(n, round(fade_in_ms / 1000.0 * sample_rate))
    fade_out = min(n - fade_in, round(fade_out_ms / 1000.0 * sample_rate))
    if fade_in > 0:
        ramp = 0.5 * (1.0 - np.cos(np.pi * np.arange(fade_in) / fade_in))
        out[:fade_in] *= ramp[:, None]
    if fade_out > 0:
        ramp = 0.5 * (1.0 - np.cos(np.pi * np.arange(fade_out) / fade_out))
        out[n - fade_out :] *= ramp[::-1][:, None]
    return out


def transient_onsets(
    mono: np.ndarray,
    sample_rate: int,
    hop_seconds: float = 0.01,
    threshold_mad: float = 6.0,
    min_rise_db: float = 3.0,
) -> np.ndarray:
    """Onset frame indices from the positive derivative of a short-window RMS.

    Cheap, time-domain and self-contained: enough to quantify *how percussive*
    the material is, which is what declick threshold selection needs. The
    ``min_rise_db`` floor keeps steady tones (whose envelope only ripples by
    numerical noise) from registering as a dense onset train.
    """
    envelope = windowed_rms(mono, sample_rate, hop_seconds * 2.0, hop_seconds)
    if envelope.size < 3:
        return np.zeros(0, dtype=np.int64)
    rise = np.diff(np.asarray(amplitude_to_db(envelope), dtype=np.float64))
    positive = np.maximum(rise, 0.0)
    sigma = 1.4826 * float(np.median(np.abs(positive - np.median(positive))))
    hot = positive > max(threshold_mad * sigma, min_rise_db)
    return np.asarray([start for start, _end in runs_of_true(hot)], dtype=np.int64)

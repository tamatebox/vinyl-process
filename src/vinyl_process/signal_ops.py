"""Pure numeric helpers shared by the analyzer and the DSP engines.

This module knows nothing about contracts or decisions. It exists so that the
analyzer's click *detection* and the native engine's click *repair* use exactly
the same arithmetic without the two layers importing each other — the one
mechanism that keeps "measure" and "execute" independent yet consistent.

Every function here is deterministic: no randomness, no wall clock.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
from scipy.linalg import solve_toeplitz
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


def block_ratio(
    mono: np.ndarray, sample_rate: int, detect_ms: float, context_ms: float
) -> npt.NDArray[np.float64]:
    """Local mean-square divided by the mean-square of its neighbourhood.

    The statistic Audacity's click detector is built on, and the reason to prefer
    it here: it is a *ratio*, so it does not care how loud the passage is, and
    both windows are local, so it does not care how much audio surrounds them.
    A single robust sigma taken over a whole side has neither property — it
    under-detects in quiet passages, over-detects wherever the material's
    high-frequency energy is bursty, and gives different answers to the analyzer
    (which sees the side) and the engine (which sees one track).
    """
    detect = max(3, round(detect_ms / 1000.0 * sample_rate))
    context = max(detect * 4, round(context_ms / 1000.0 * sample_rate))
    energy = np.asarray(mono, dtype=np.float64) ** 2
    cumulative = np.concatenate([[0.0], np.cumsum(energy)])

    def centred_mean(width: int) -> npt.NDArray[np.float64]:
        half = width // 2
        starts = np.clip(np.arange(energy.size) - half, 0, energy.size)
        ends = np.clip(starts + width, 0, energy.size)
        starts = np.minimum(starts, ends)
        counts = np.maximum(ends - starts, 1)
        means = (cumulative[ends] - cumulative[starts]) / counts
        return np.asarray(means, dtype=np.float64)

    return centred_mean(detect) / (centred_mean(context) + EPS)


def click_events_block_sweep(
    mono: np.ndarray,
    sample_rate: int,
    thresholds: Sequence[float],
    max_width_ms: float,
    detect_ms: float = 0.2,
    context_ms: float = 40.0,
    highpass_hz: float = 3000.0,
) -> dict[float, list[ClickEvent]]:
    """The detector run at several thresholds, sharing one pass of the arithmetic.

    Everything expensive — the high-pass, the two running means, the curvature —
    is independent of the threshold, so a whole ladder costs barely more than a
    single point. That matters because **no single threshold is right for every
    pressing**: on one album measured here the two sides wanted different values,
    and a collection spans conditions from near-mint to heavily worn. Reporting
    the ladder lets the choice be made per record, from evidence, by whoever owns
    it — which is where a threshold belongs. A constant compiled in here would be
    a decision taken on behalf of every record the code will ever see.
    """
    if mono.size == 0:
        return {float(t): [] for t in thresholds}
    max_width = max(1, round(max_width_ms / 1000.0 * sample_rate))
    detection = highpass(mono, sample_rate, highpass_hz)
    ratio = block_ratio(detection, sample_rate, detect_ms, context_ms)
    # Within half a context window of either edge the neighbourhood is padding
    # rather than signal, so that region is declared undetectable.
    guard = min(round(context_ms / 1000.0 * sample_rate) // 2, ratio.size // 2)
    if guard:
        ratio[:guard] = 0.0
        ratio[-guard:] = 0.0
    curvature = second_difference(mono)
    curvature_sigma = 1.4826 * float(np.median(np.abs(curvature - np.median(curvature))))
    return {
        float(threshold): _localised_events(
            ratio > threshold, detection, curvature, curvature_sigma, max_width
        )
        for threshold in thresholds
    }


def click_events_block(
    mono: np.ndarray,
    sample_rate: int,
    threshold_ratio: float,
    max_width_ms: float,
    detect_ms: float = 0.2,
    context_ms: float = 40.0,
    highpass_hz: float = 3000.0,
) -> list[ClickEvent]:
    """Detect impulsive clicks by local-to-neighbourhood energy ratio.

    ``threshold_ratio`` is how many times the energy in a click-width window
    must exceed the energy of the surrounding ``context_ms`` to count as damage.
    It is **not** a sigma count, and no one value suits two pressings; see
    :func:`click_events_block_sweep`.

    This replaced a detector that thresholded a robust sigma taken over the whole
    input. That statistic is not local: handed the same 60 s in different chunk
    sizes it moved its answer by up to 7.8x, so the analyzer (a side) and the
    engine (a track) described different events. On a near-clean pressing it also
    claimed 1082 events a minute while finding none at all in the inter-track
    gaps, where the surface is unmasked — over-detecting and missing at once.

    The high-pass runs first: a click is broadband while programme material is
    concentrated lower, and the ratio alone would fire on any percussive attack.
    It fires on some anyway — see the caveat in ``docs/dsp-engines.md``.

    ``detect_ms`` and ``context_ms`` are carried over from Audacity's detector,
    whose surrounding window is about 2048 samples. They have not been tested
    against anything here; only the *shape* of the statistic has.
    """
    return click_events_block_sweep(
        mono,
        sample_rate,
        [threshold_ratio],
        max_width_ms,
        detect_ms=detect_ms,
        context_ms=context_ms,
        highpass_hz=highpass_hz,
    )[float(threshold_ratio)]


def _localised_events(
    hot: np.ndarray,
    detection: np.ndarray,
    curvature: np.ndarray,
    curvature_sigma: float,
    max_width: int,
) -> list[ClickEvent]:
    """Thresholded samples to localised, width-checked spans."""
    if not hot.any():
        return []
    events: list[ClickEvent] = []
    for start, end in merge_runs(runs_of_true(hot), gap=max_width):
        span_start, span_end = _localise(curvature, start, end, 6.0 * curvature_sigma, max_width)
        if span_end - span_start > max_width:
            continue
        # The click's own amplitude, taken from the high-passed signal: the raw
        # sample would include whatever music sits under the impulse.
        peak = float(np.max(np.abs(detection[span_start:span_end])))
        events.append((span_start, span_end, peak))
    return events


def ar_coefficients(segment: np.ndarray, order: int) -> npt.NDArray[np.float64]:
    """Yule-Walker AR coefficients, so ``x[n] ~ sum a[k] * x[n-k-1]``."""
    x = np.asarray(segment, dtype=np.float64)
    order = max(1, min(order, x.size - 2))
    autocorrelation = np.correlate(x, x, mode="full")[x.size - 1 : x.size + order]
    if autocorrelation[0] <= EPS:
        return np.zeros(order, dtype=np.float64)
    # Ridge the diagonal: on near-silent or perfectly periodic material the
    # Toeplitz system is singular, and a solve that fails is worse than a
    # slightly biased model.
    r = autocorrelation / autocorrelation[0]
    r[0] += 1e-9
    try:
        coefficients = solve_toeplitz(r[:order], r[1 : order + 1])
    except (np.linalg.LinAlgError, ValueError):
        return np.zeros(order, dtype=np.float64)
    return np.asarray(coefficients, dtype=np.float64)


def _ar_fill(
    channel: np.ndarray, lo: int, hi: int, order: int, iterations: int, context: int
) -> npt.NDArray[np.float64]:
    """Janssen's alternation for one gap in one channel.

    Estimate an AR model from the audio around the gap, solve for the missing
    samples that the model explains best, and repeat. Unlike a polynomial the
    model can reproduce oscillation, which is what the missing samples of an
    audio signal almost always contain — a cubic can only draw a smooth arc
    through them.
    """
    n = channel.size
    start = max(0, lo + 1 - context)
    stop = min(n, hi + context)
    segment = channel[start:stop].astype(np.float64, copy=True)
    gap = np.arange(lo + 1 - start, hi - start, dtype=np.int64)
    if gap.size == 0 or segment.size <= order + 2:
        return channel[lo + 1 : hi].astype(np.float64, copy=True)

    # Seed with a straight line: bounded by construction, so a failed solve
    # degrades to Audacity's answer rather than to a divergent one.
    left = segment[gap[0] - 1] if gap[0] >= 1 else segment[gap[-1] + 1]
    right = segment[gap[-1] + 1] if gap[-1] + 1 < segment.size else left
    weights = (np.arange(1, gap.size + 1, dtype=np.float64) / (gap.size + 1))[:, None]
    segment[gap] = ((1.0 - weights) * left + weights * right).ravel()

    for _ in range(max(1, iterations)):
        a = ar_coefficients(segment, order)
        p = a.size
        rows = np.arange(int(gap[0]), min(segment.size, int(gap[-1]) + p + 1), dtype=np.int64)
        rows = rows[rows >= p]
        if rows.size == 0:
            break
        # Residual coefficient of unknown j in row i: +1 where the row predicts
        # that sample, -a[k] where the sample is one of its predictors.
        distance = rows[:, None] - gap[None, :]
        matrix = (distance == 0).astype(np.float64)
        inside = (distance >= 1) & (distance <= p)
        matrix -= np.where(inside, a[np.clip(distance - 1, 0, p - 1)], 0.0)
        known = segment.copy()
        known[gap] = 0.0
        predictors = np.lib.stride_tricks.sliding_window_view(known, p)
        residual = known[rows] - (predictors[rows - p][:, ::-1] * a[None, :]).sum(axis=1)
        try:
            solution, *_ = np.linalg.lstsq(matrix, -residual, rcond=None)
        except np.linalg.LinAlgError:
            break
        segment[gap] = solution
    return np.asarray(segment[gap], dtype=np.float64)


def repair_clicks_linear(
    samples: np.ndarray, events: list[ClickEvent], strength: float
) -> np.ndarray:
    """Bridge each click with a straight line, blended by ``strength``.

    What Audacity's click removal does, and the reason to keep it available: a
    line between two samples cannot leave the range they span, so it cannot
    diverge for any gap width or any material. It is the crude option and it wins
    where the cubic fails — measured against damage injected into a real transfer,
    it beat the bounded cubic at 65-sample gaps while losing to it at 4-sample
    ones. No parameters at all, which is worth something on its own.
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
        t = (np.arange(1, gap + 1, dtype=np.float64) / (gap + 1))[:, None]
        patch = (1.0 - t) * out[lo][None, :] + t * out[hi][None, :]
        out[lo + 1 : hi] = (1.0 - strength) * out[lo + 1 : hi] + strength * patch
    return out


def repair_clicks_ar(
    samples: np.ndarray,
    events: list[ClickEvent],
    strength: float,
    order: int = 32,
    iterations: int = 3,
    context: int = 256,
) -> np.ndarray:
    """Bridge each click by AR least squares (Janssen), blended by ``strength``.

    The textbook answer to this problem — Janssen 1986, and the method behind
    Godsill & Rayner's *Digital Audio Restoration* — and still a state-of-the-art
    baseline. Deterministic, needs no training data, and for the gap lengths a
    vinyl click leaves (a fraction of a millisecond) it reconstructs the
    oscillation the polynomial had to smooth over.

    Every channel is repaired over the same time window so stereo imaging is
    preserved, but the model is fitted per channel: the two carry different
    material and one AR model for their sum would fit neither.

    The result is still clipped into :func:`local_bounds`. A model-based fill has
    no reason to diverge, and this is the belt to that braces: the contract is
    that no repair invents a level its neighbourhood never reaches, and it holds
    for every interpolator here or it is not a contract.
    """
    out = np.array(samples, dtype=np.float64, copy=True)
    n = out.shape[0]
    if n == 0 or strength <= 0.0:
        return out
    for start, end, _peak in events:
        lo = start - 1
        hi = min(end, n - 1)
        if lo < 0 or hi - lo - 1 <= 0:
            continue
        patch = np.column_stack(
            [
                _ar_fill(out[:, channel], lo, hi, order, iterations, context)
                for channel in range(out.shape[1])
            ]
        )
        low, high = local_bounds(out, lo, hi, max(CONTEXT_FLOOR, 2 * (hi - lo)))
        patch = np.clip(patch, low[None, :], high[None, :])
        out[lo + 1 : hi] = (1.0 - strength) * out[lo + 1 : hi] + strength * patch
    return out


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


CONTEXT_FLOOR = 16
"""Smallest neighbourhood used to bound a repair. See :func:`local_bounds`."""


def local_bounds(
    samples: np.ndarray, lo: int, hi: int, reach: int
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Per-channel min and max of the good audio on either side of a gap.

    A repair may not invent a level the surrounding music never reaches. Any
    interpolator that leaves this range has failed rather than succeeded, so the
    range is the contract every repair here is held to.
    """
    n = samples.shape[0]
    before = samples[max(0, lo - reach) : lo + 1]
    after = samples[hi : min(n, hi + reach + 1)]
    context = (
        np.concatenate([before, after])
        if before.size and after.size
        else (before if before.size else after)
    )
    return context.min(axis=0), context.max(axis=0)


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

    The bridge is then clipped into :func:`local_bounds`. Hermite's tangent term
    carries a factor of the span, so on broadband material — where the per-sample
    slope is comparable to the amplitude itself — a legitimately narrow gap can
    still make the cubic diverge. Measured on a real transfer: a 65-sample gap
    whose neighbourhood peaked at 0.071 was bridged at 0.892, twelve times the
    surrounding audio and three times the whole track's true peak. Clipping is
    the floor under that, not a substitute for an interpolator that models the
    signal (see ``repair_clicks_ar``).
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
        low, high = local_bounds(out, lo, hi, max(CONTEXT_FLOOR, 2 * span))
        patch = np.clip(patch, low[None, :], high[None, :])
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

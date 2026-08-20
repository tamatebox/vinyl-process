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
from scipy.signal import butter, resample_poly, sosfilt, sosfiltfilt

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


TRUE_PEAK_OVERSAMPLE = 4
"""Oversampling factor ITU-R BS.1770-4 specifies for true-peak metering."""

GATE_BLOCK_SECONDS = 0.4
GATE_HOP_SECONDS = 0.1
"""BS.1770-4's gating geometry: 400 ms blocks overlapping by 75 %."""

ABSOLUTE_GATE_DB = -70.0
RELATIVE_GATE_DB = -10.0
"""BS.1770-4's two gate thresholds, the second relative to the absolute-gated mean."""

_TRUE_PEAK_CHUNK = 1 << 19
_TRUE_PEAK_MARGIN = 1 << 12


def true_peak(samples: np.ndarray, oversample: int = TRUE_PEAK_OVERSAMPLE) -> float:
    """Peak of the *reconstructed* waveform, as linear amplitude.

    A sample-peak reading sees only the stored samples, so it misses the
    inter-sample peaks any reconstruction filter puts back: material reading
    -0.1 dBFS can reconstruct above 0 dBTP, and a resampler or a lossy encoder
    then realises that as a real sample. BS.1770-4 estimates the true ceiling by
    oversampling 4x before taking the maximum, which is what this does — with a
    polyphase FIR rather than the standard's exact filter, so it is a close
    estimate and not a certified reading.

    The result is an upper bound on the sample peak of *any* later resampling of
    the same material, which is what makes it the right quantity to hold a
    ceiling against.

    Chunked with overlap, because a 20-minute side upsampled 4x in one piece
    would need gigabytes. Only the interior of each chunk is read, so the
    zero-padded chunk edges cannot contribute a spurious maximum.
    """
    data = np.asarray(samples, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, None]
    if data.size == 0:
        return 0.0
    frames = data.shape[0]
    if oversample <= 1 or frames < 4 * oversample:
        return float(np.max(np.abs(data)))

    margin = min(_TRUE_PEAK_MARGIN, frames)
    peak = 0.0
    for start in range(0, frames, _TRUE_PEAK_CHUNK):
        stop = min(start + _TRUE_PEAK_CHUNK, frames)
        left = min(margin, start)
        right = min(margin, frames - stop)
        block = resample_poly(data[start - left : stop + right], oversample, 1, axis=0)
        interior = block[left * oversample : block.shape[0] - right * oversample]
        peak = max(peak, float(np.max(np.abs(interior))))
    return peak


def rms_blocks(
    samples: np.ndarray,
    sample_rate: int,
    *,
    block_seconds: float = GATE_BLOCK_SECONDS,
    hop_seconds: float = GATE_HOP_SECONDS,
) -> npt.NDArray[np.float64]:
    """Per-block RMS (linear amplitude) on BS.1770-4's block geometry.

    Channels are averaged, not summed, so a value is directly comparable with
    the plain ``peaks.rms_db`` of the same material. Kept separate from
    :func:`gated_rms_of_blocks` so an album-wide measurement can pool the blocks
    of every track before gating — the same rule ReplayGain's album gain uses.
    """
    data = np.asarray(samples, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, None]
    if data.size == 0:
        return np.zeros(0)
    mono = np.sqrt(np.mean(data**2, axis=1))
    return windowed_rms(mono, sample_rate, block_seconds, hop_seconds)


def gated_rms_of_blocks(blocks: npt.NDArray[np.float64]) -> float:
    """Apply BS.1770-4's two gates to pooled blocks and return the RMS of what
    survives, as linear amplitude.

    An ungated average over a whole side counts the inter-track gaps, the fades
    and the lead-in as programme, so a side with long gaps measures quieter than
    it sounds — and after normalization to a fixed RMS target it comes out too
    loud. The absolute gate drops silence; the relative gate, 10 dB under the
    mean of what the absolute gate left, drops the quiet tail.

    The gates and the geometry are BS.1770-4's; the K-weighting is *not* applied,
    so this is a level measurement in dBFS and never loudness in LUFS.
    """
    if blocks.size == 0:
        return 0.0
    surviving = blocks[np.asarray(amplitude_to_db(blocks)) > ABSOLUTE_GATE_DB]
    if surviving.size == 0:
        # Everything is below the absolute gate: the material really is silence,
        # and reporting its level is more useful than reporting nothing.
        return float(np.sqrt(np.mean(blocks**2)))
    ungated = float(np.sqrt(np.mean(surviving**2)))
    threshold = float(amplitude_to_db(ungated)) + RELATIVE_GATE_DB
    loud = surviving[np.asarray(amplitude_to_db(surviving)) > threshold]
    if loud.size == 0:  # pragma: no cover - a flat signal sits exactly on the gate
        loud = surviving
    return float(np.sqrt(np.mean(loud**2)))


def gated_rms(samples: np.ndarray, sample_rate: int) -> float:
    """:func:`rms_blocks` followed by :func:`gated_rms_of_blocks`, for one buffer."""
    return gated_rms_of_blocks(rms_blocks(samples, sample_rate))


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


def remove_dc(samples: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Subtract each channel's own mean from ``(frames, channels)`` audio.

    Exact rather than approximate, and with no transition band: a DC offset is a
    constant, so removing it costs nothing at any audible frequency. This is the
    quantity ``recording_info.dc_offset`` reports.
    """
    if samples.size == 0:
        return np.asarray(samples, dtype=np.float64)
    values = np.asarray(samples, dtype=np.float64)
    return np.ascontiguousarray(values - values.mean(axis=0, keepdims=True))


def subsonic_highpass(
    samples: npt.NDArray[np.float64], sample_rate: int, cutoff_hz: float, order: int
) -> npt.NDArray[np.float64]:
    """Butterworth high-pass across every channel, applied **forward only**.

    Forward-only, not zero-phase, and that is the whole point: a Butterworth of
    order *n* rolls off at 6·*n* dB/octave in one pass, and the reference practice
    this implements is stated in dB/octave (24, i.e. order 4). Running it through
    ``sosfiltfilt`` would double the effective rolloff, so a plan asking for 24
    would silently get 48 — exactly the kind of mismatch between a stated number
    and a delivered one that this project treats as a defect.

    The cost is phase shift near the cutoff and a settling transient at the head
    of the buffer. Both live below 30 Hz on a subsonic filter, which is where
    nothing is audible; ``sosfilt`` is deterministic, so the output still
    reproduces bit for bit.

    Returns the input unchanged when the cutoff is not usefully below Nyquist, or
    when the buffer is too short for the filter to mean anything.
    """
    values = np.asarray(samples, dtype=np.float64)
    nyquist = sample_rate / 2.0
    if cutoff_hz <= 0 or cutoff_hz >= nyquist * 0.98 or values.shape[0] < 3 * order:
        return values
    sos = butter(order, cutoff_hz / nyquist, btype="highpass", output="sos")
    return np.ascontiguousarray(sosfilt(sos, values, axis=0), dtype=np.float64)


def crackle_events_curvature(
    mono: np.ndarray,
    threshold_ratio: float,
    max_width_samples: int,
    context_ms: float = 5.0,
    sample_rate: int = 44100,
) -> list[ClickEvent]:
    """Per-sample outlier detection for crackle: 1-3 sample events, densely repeated.

    A different question from :func:`click_events_block`, and deliberately a
    different algorithm. ``block_ratio`` asks whether a *segment* is an outlier
    against its neighbourhood — a collective decision, and the right one for a
    discrete impulse of a few hundred microseconds. Crackle is a bed of one-to-three
    sample events, each a weak outlier and there are thousands, so a collective
    threshold low enough to catch them starts interpolating the music long before it
    clears the bed. The tool for it examines **every sample individually**.

    So the statistic here is per sample: ``|curvature|`` against the mean
    ``|curvature|`` of its own neighbourhood. Two properties are carried over from
    ``block_ratio`` on purpose. It is a **ratio**, so a quiet passage and a loud one
    are judged alike. And it is **local**, so the answer does not depend on how much
    audio the function was handed, which is what lets an analyzer and an engine
    agree — see ``docs/adr/0010-the-click-statistic-is-local.md``.

    ``threshold_ratio`` is that ratio, so **smaller is more aggressive**. It is not
    ClickRepair's DeCrackle sensitivity, whose scale runs the other way and is "an
    arbitrary percentage"; only that tool's *repair-rate band* transfers.

    Runs wider than ``max_width_samples`` are dropped rather than repaired: at that
    width the event is a click, and ``declick`` is what handles those. This function
    therefore cannot bridge anything the click detector would have found, which is
    what keeps the two stages from fighting over the same samples.
    """
    values = np.asarray(mono, dtype=np.float64)
    if values.size < 3 or threshold_ratio <= 0 or max_width_samples < 1:
        return []
    curvature = np.abs(second_difference(values))
    context = max(3, round(context_ms / 1000.0 * sample_rate))
    cumulative = np.concatenate([[0.0], np.cumsum(curvature)])
    half = context // 2
    starts = np.clip(np.arange(curvature.size) - half, 0, curvature.size)
    ends = np.clip(starts + context, 0, curvature.size)
    starts = np.minimum(starts, ends)
    counts = np.maximum(ends - starts, 1)
    local_mean = (cumulative[ends] - cumulative[starts]) / counts
    ratio = curvature / (local_mean + EPS)

    # The first and last sample have no curvature (second_difference pads with
    # zero), so they can never be outliers; nothing to guard beyond that, because
    # the statistic needs no filter warm-up.
    events: list[ClickEvent] = []
    for start, end in runs_of_true(ratio > threshold_ratio):
        if end - start > max_width_samples:
            continue
        peak = float(np.max(np.abs(values[start:end])))
        events.append((start, end, peak))
    return events


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


def onset_coincidence(
    mono: np.ndarray, positions: Sequence[int], sample_rate: int, window_ms: float = 10.0
) -> float:
    """How much more often than chance these positions sit on a rising edge.

    A detection that lands where the signal jumps is probably the thing that made
    it jump. Comparing the share of detections on a rise against the share of *all*
    positions on a rise turns that into a number: 1.0 means the detector is
    indifferent to onsets, and large means it is following the music.

    This is the check that a gap-versus-programme rate cannot make. On one
    pressing a threshold whose silence rate beat its programme rate 43.8 to 1 was
    still landing on onsets 7.8 times more often than chance, and a lower rung
    accepted by the same ratio produced detections spaced at the beat rather than
    at the platter's revolution. The control is a fixed stride rather than random
    samples, so the figure is reproducible.
    """
    x = np.asarray(mono, dtype=np.float64)
    window = max(2, round(window_ms / 1000.0 * sample_rate))
    if x.size < 4 * window or not len(positions):
        return float("nan")
    cumulative = np.concatenate([[0.0], np.cumsum(x**2)])

    def rise_db(index: npt.NDArray[np.int64]) -> npt.NDArray[np.float64]:
        before = cumulative[index] - cumulative[index - window]
        after = cumulative[index + window] - cumulative[index]
        return np.asarray(10.0 * np.log10((after + EPS) / (before + EPS)), dtype=np.float64)

    grid = np.arange(window, x.size - window, 64, dtype=np.int64)
    found = np.asarray([p for p in positions if window <= p < x.size - window], dtype=np.int64)
    if grid.size == 0 or found.size == 0:
        return float("nan")
    control = max(float((rise_db(grid) > 6.0).mean()), 1.0 / grid.size)
    return round(float((rise_db(found) > 6.0).mean()) / control, 2)


def phase_concentration(
    positions: Sequence[int], sample_rate: int, period_seconds: float
) -> tuple[float, float]:
    """How tightly these positions cluster at one phase of a repeating period.

    Returns ``(r, z)``. ``r`` is the mean resultant length of the positions folded
    onto the period — 0 for phases spread evenly, 1 for all at the same phase.
    ``z = n * r**2`` is Rayleigh's statistic, whose null distribution is
    exponential with mean 1 whatever ``n`` is, so rungs with different counts are
    directly comparable: 3 is suggestive, 5 strong, and 1 is what chance gives.

    The period this matters for is the platter's, because a defect that crosses
    the groove spiral is struck once per revolution — 1.8 s at 33 1/3 rpm, 1.333 s
    at 45. That is the one kind of surface damage a naive "periodic means music"
    rule would throw away, and it is the most audible kind: a tick you can set a
    watch by. Unlike the beat, the period is known in advance from the speed the
    record was played at, so nothing has to be estimated.
    """
    found = np.asarray(list(positions), dtype=np.float64)
    if found.size < 4 or period_seconds <= 0 or sample_rate <= 0:
        return float("nan"), float("nan")
    phase = 2.0 * np.pi * ((found / sample_rate) % period_seconds) / period_seconds
    r = float(np.abs(np.exp(1j * phase).mean()))
    return round(r, 4), round(found.size * r * r, 2)


def sinusoidal_residual(segment: np.ndarray, components: int = 5) -> npt.NDArray[np.float64]:
    """``segment`` windowed, minus a reconstruction from its strongest partials.

    Few components on purpose: a handful of sinusoids can represent tonal
    material but not an impulse, so what survives the subtraction at a real click
    is the click. Both sides are windowed, which is why no deconvolution is
    needed and why the taper keeps the edges from dominating — the candidate sits
    at the centre by construction.
    """
    n = segment.size
    if n < 16:
        return np.zeros(n, dtype=np.float64)
    windowed = np.asarray(segment, dtype=np.float64) * np.hanning(n)
    spectrum = np.fft.rfft(windowed)
    magnitude = np.abs(spectrum)
    interior = np.arange(1, magnitude.size - 1)
    peaks = interior[(magnitude[1:-1] > magnitude[:-2]) & (magnitude[1:-1] >= magnitude[2:])]
    if peaks.size == 0:
        peaks = np.array([int(np.argmax(magnitude))])
    chosen = peaks[np.argsort(magnitude[peaks])[::-1][:components]]
    keep = np.zeros(magnitude.size, dtype=bool)
    for index in chosen:
        # a windowed sinusoid occupies a lobe, not a bin
        keep[max(0, index - 1) : min(magnitude.size, index + 2)] = True
    model = np.fft.irfft(np.where(keep, spectrum, 0.0), n=n)
    return np.asarray(windowed - model, dtype=np.float64)


def confirm_clicks_sinusoidal(
    mono: np.ndarray,
    events: list[ClickEvent],
    k: float,
    components: int = 5,
    margin: int = 50,
) -> list[ClickEvent]:
    """Discard candidates a few sinusoids can already explain.

    After Alvarez, Mendez & Langwagen (DAFx 2004). For each candidate, model the
    audio from ``margin`` samples before it to ``margin`` after with
    ``components`` partials, and keep it only if the residual inside its span
    exceeds ``k`` standard deviations of that residual over the window.

    The point is that it lets the *detector* be sensitive. Raising a detection
    threshold until it stops firing on the music also stops it firing on quiet
    clicks; a confirmation stage separates the two decisions. Measured on one
    pressing, a rung whose detections landed on onsets 13.3 times more often than
    chance came down to indifference under this test while keeping its detections
    in the inter-track gaps.

    ``k`` is a decision and has no default here: the paper's 3 left the onset bias
    almost untouched on the pressing measured, which needed 5. Choose it by
    raising it until :func:`onset_coincidence` stops exceeding 1, and record the
    value in the plan.
    """
    kept: list[ClickEvent] = []
    for start, end, peak in events:
        lo = max(0, start - margin)
        hi = min(mono.size, end + margin)
        if hi - lo < 32:
            continue
        residual = sinusoidal_residual(mono[lo:hi], components)
        threshold = k * float(np.std(residual))
        span = residual[start - lo : max(start - lo + 1, end - lo)]
        if float(np.max(np.abs(span))) > threshold:
            kept.append((start, end, peak))
    return kept


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


def onset_flux(
    mono: np.ndarray,
    sample_rate: int,
    window_seconds: float = 0.02,
    hop_seconds: float = 0.005,
) -> npt.NDArray[np.float64]:
    """Spectral-flux onset strength per frame, mean removed.

    The positive part of the frame-to-frame change in magnitude spectrum, summed
    over bins. Unlike :func:`transient_onsets` this keeps a continuous strength
    rather than thresholding to onset positions, because what it feeds —
    :func:`periodicity_peaks` — needs to see a *weak but regular* pulse train
    that no threshold would keep.

    Computed in chunks so a full album side does not materialise its own STFT.
    """
    window = max(4, round(window_seconds * sample_rate))
    hop = max(1, round(hop_seconds * sample_rate))
    samples = np.asarray(mono, dtype=np.float64)
    if samples.size < window + hop:
        return np.zeros(0, dtype=np.float64)

    taper = np.hanning(window)
    frames = (samples.size - window) // hop + 1
    flux = np.zeros(frames - 1, dtype=np.float64)
    previous: npt.NDArray[np.float64] | None = None
    chunk = max(1, (1 << 20) // max(1, window))
    for start in range(0, frames, chunk):
        stop = min(frames, start + chunk)
        offsets = np.arange(start, stop) * hop
        block = samples[offsets[:, None] + np.arange(window)[None, :]] * taper
        magnitude = np.abs(np.fft.rfft(block, axis=1))
        if previous is not None:
            flux[start - 1] = float(np.maximum(magnitude[0] - previous, 0.0).sum())
        rise = np.maximum(np.diff(magnitude, axis=0), 0.0).sum(axis=1)
        flux[start : start + rise.size] = rise
        previous = magnitude[-1]
    return np.asarray(flux - flux.mean(), dtype=np.float64)


def periodicity_peaks(
    flux: np.ndarray,
    frame_rate: float,
    min_period_seconds: float,
    max_period_seconds: float,
    top_k: int = 3,
) -> tuple[list[tuple[float, float]], float]:
    """Autocorrelation peaks of an onset-strength envelope, with its baseline.

    Returns ``([(period_seconds, r), ...], baseline_r)`` — up to ``top_k`` peaks
    ordered by correlation, and the median correlation across the search range.

    The baseline is reported because a peak means nothing without the floor it
    stands on. A broad, slowly modulated envelope — dense crackle, say — raises
    the correlation everywhere at once, so a raw ``r`` read off it can match real
    music; a clean tick train, by contrast, leaves the median near zero and
    spikes only at its own multiples. Subtract the median before comparing one
    window's peak against another's.
    """
    envelope = np.asarray(flux, dtype=np.float64)
    lo = max(1, round(min_period_seconds * frame_rate))
    hi = round(max_period_seconds * frame_rate)
    if envelope.size < 2 * hi or hi <= lo:
        return [], 0.0

    envelope = envelope - envelope.mean()
    energy = float(envelope @ envelope)
    if energy <= EPS:
        return [], 0.0
    correlation = np.correlate(envelope, envelope, mode="full")[envelope.size - 1 :] / energy

    window = correlation[lo:hi]
    baseline = float(np.median(window))
    guard = max(1, round(0.08 * frame_rate))
    peaks: list[tuple[float, float]] = []
    for index in np.argsort(window)[::-1]:
        lag = int(index) + lo
        if any(abs(lag - round(period * frame_rate)) < guard for period, _ in peaks):
            continue
        peaks.append((lag / frame_rate, float(window[index])))
        if len(peaks) == top_k:
            break
    return peaks, baseline


def correlation_at(flux: np.ndarray, lag: int) -> float:
    """Normalised autocorrelation of an onset envelope at one lag.

    Zero when the lag does not fit the envelope, so a caller can ask about a
    fixed period — one turn of the disc, say — without first checking length.
    """
    envelope = np.asarray(flux, dtype=np.float64)
    if lag <= 0 or envelope.size <= lag:
        return 0.0
    envelope = envelope - envelope.mean()
    energy = float(envelope @ envelope)
    if energy <= EPS:
        return 0.0
    return float(envelope[:-lag] @ envelope[lag:]) / energy

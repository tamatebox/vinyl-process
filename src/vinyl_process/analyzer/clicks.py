"""Click statistics — measurement only; repair lives in the DSP layer.

Detection is shared with the native declick engine through
:mod:`vinyl_process.signal_ops`, so the statistics a skill reasons about and the
damage the engine repairs are the same events by construction.
"""

from __future__ import annotations

import numpy as np

from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.analyzer.registry import analyzer
from vinyl_process.models.analysis import ClicksSection, Histogram
from vinyl_process.models.common import SectionMeta
from vinyl_process.signal_ops import amplitude_to_db, click_events

AMPLITUDE_BINS_DB: tuple[float, ...] = (-90.0, -60.0, -50.0, -40.0, -30.0, -20.0, -10.0, 0.0)
WIDTH_BINS_MS: tuple[float, ...] = (0.0, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0)


def _histogram(values: np.ndarray, edges: tuple[float, ...], unit: str) -> Histogram:
    """Histogram whose outer bins are inclusive of everything beyond them.

    Values are clipped into range first, so ``sum(counts) == len(values)`` always
    holds. Dropping out-of-range clicks would make the histogram disagree with
    ``count`` — and a repaired record's leftovers land well below the lowest bin.
    """
    clipped = np.clip(values, edges[0], edges[-1]) if values.size else values
    counts, _ = np.histogram(clipped, bins=list(edges))
    return Histogram(unit=unit, bin_edges=list(edges), counts=[int(count) for count in counts])


@analyzer(
    name="clicks",
    version="1.0",
    description="Click count, rate, amplitude and width histograms, density over time.",
    defaults={
        "threshold_mad": 6.0,
        "max_width_ms": 3.0,
        "highpass_hz": 3000.0,
        "max_positions": 5000,
    },
)
def analyze_clicks(context: AnalyzerContext) -> ClicksSection:
    audio = context.audio
    max_width_ms = context.number("max_width_ms")
    events = click_events(
        audio.mono(),
        audio.sample_rate,
        context.number("threshold_mad"),
        max_width_ms,
        highpass_hz=context.number("highpass_hz"),
    )

    peaks_db = np.asarray([amplitude_to_db(peak) for _s, _e, peak in events], dtype=np.float64)
    widths_ms = np.asarray(
        [(end - start) / audio.sample_rate * 1000.0 for start, end, _p in events],
        dtype=np.float64,
    )
    positions = [start for start, _e, _p in events]
    limit = context.integer("max_positions")
    minutes = max(audio.duration_seconds / 60.0, 1e-9)

    return ClicksSection(
        # The detector is a robust-statistics estimator, not ground truth: it is
        # reliable about *relative* damage, less so about absolute counts.
        meta=SectionMeta(confidence=0.75),
        count=len(events),
        rate_per_minute=round(len(events) / minutes, 2),
        amplitude_histogram=_histogram(peaks_db, AMPLITUDE_BINS_DB, "dBFS"),
        width_histogram=_histogram(widths_ms, WIDTH_BINS_MS, "ms"),
        density_per_minute=_density_per_minute(positions, audio.sample_rate, audio.num_frames),
        positions_sample=positions[:limit],
        positions_truncated=len(positions) > limit,
    )


def _density_per_minute(positions: list[int], sample_rate: int, num_frames: int) -> list[float]:
    """Clicks per one-minute bucket, so a skill can see localised damage."""
    if num_frames == 0:
        return []
    buckets = max(1, int(np.ceil(num_frames / (sample_rate * 60.0))))
    counts = np.zeros(buckets, dtype=np.float64)
    for position in positions:
        counts[min(buckets - 1, int(position // (sample_rate * 60)))] += 1.0
    return [float(c) for c in counts]

"""Level measurements: peaks, dynamic range and clipping."""

from __future__ import annotations

import numpy as np

from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.analyzer.registry import analyzer
from vinyl_process.models.analysis import (
    ClippingSection,
    DynamicRangeSection,
    PeaksSection,
    Percentiles,
    RmsProfileSection,
)
from vinyl_process.models.common import SectionMeta
from vinyl_process.signal_ops import (
    EPS,
    TRUE_PEAK_OVERSAMPLE,
    amplitude_to_db,
    gated_rms,
    runs_of_true,
    true_peak,
)


@analyzer(
    name="peaks",
    version="1.0",
    description="Sample peak, true peak, overall and gated RMS, crest factor.",
    defaults={"true_peak_oversample": TRUE_PEAK_OVERSAMPLE},
)
def analyze_peaks(context: AnalyzerContext) -> PeaksSection:
    audio = context.audio
    samples = audio.samples
    magnitude = np.abs(samples)
    peak_index = int(np.argmax(magnitude.max(axis=1)))
    peak = float(magnitude[peak_index].max())
    rms = float(np.sqrt(np.mean(samples**2) + EPS))
    peak_db = float(amplitude_to_db(peak))
    rms_db = float(amplitude_to_db(rms))
    oversample = context.integer("true_peak_oversample")
    # Both extra figures are still direct measurements, so the confidence stays
    # 1.0 — the true peak is an estimate of a *different* quantity, not a
    # guess at this one.
    reconstructed = float(amplitude_to_db(true_peak(samples, oversample)))
    programme = float(amplitude_to_db(gated_rms(samples, audio.sample_rate)))
    return PeaksSection(
        meta=SectionMeta(confidence=1.0),
        peak_db=round(peak_db, 2),
        peak_sample=peak_index,
        true_peak_db=round(max(reconstructed, peak_db), 2),
        rms_db=round(rms_db, 2),
        gated_rms_db=round(programme, 2),
        crest_factor_db=round(peak_db - rms_db, 2),
    )


@analyzer(
    name="dynamic_range",
    version="1.0",
    description="Peak-to-loud-RMS estimate and the RMS distribution.",
    requires=("rms_profile", "peaks"),
)
def analyze_dynamic_range(context: AnalyzerContext) -> DynamicRangeSection:
    profile = context.typed_section("rms_profile", RmsProfileSection)
    peaks = context.typed_section("peaks", PeaksSection)
    values = np.asarray(profile.values_db, dtype=np.float64)
    if values.size == 0:
        loud = peaks.rms_db
        percentiles = Percentiles(p05_db=loud, p50_db=loud, p95_db=loud)
    else:
        loud = float(np.percentile(values, 95))
        percentiles = Percentiles(
            p05_db=round(float(np.percentile(values, 5)), 2),
            p50_db=round(float(np.percentile(values, 50)), 2),
            p95_db=round(loud, 2),
        )
    return DynamicRangeSection(
        # A window-based approximation of the DR metric, not the certified one.
        meta=SectionMeta(confidence=0.7),
        dr_estimate_db=round(peaks.peak_db - loud, 2),
        loud_rms_db=round(loud, 2),
        percentiles=percentiles,
    )


@analyzer(
    name="clipping",
    version="1.0",
    description="Full-scale sample runs that indicate a clipped capture.",
    defaults={"clip_level": 0.9999, "min_run_samples": 3},
)
def analyze_clipping(context: AnalyzerContext) -> ClippingSection:
    audio = context.audio
    hot = np.abs(audio.samples).max(axis=1) >= context.number("clip_level")
    total = int(hot.sum())
    runs = runs_of_true(hot)
    min_run = context.integer("min_run_samples")
    long_runs = [(start, end) for start, end in runs if end - start >= min_run]
    longest = max((end - start for start, end in runs), default=0)
    # Isolated full-scale samples can be legitimate peaks; runs are near-certain.
    confidence = 0.98 if long_runs or total == 0 else 0.6
    return ClippingSection(
        meta=SectionMeta(confidence=confidence),
        clipped_sample_count=total,
        clipped_region_count=len(long_runs),
        longest_run_samples=longest,
        ratio=round(total / max(audio.num_frames, 1), 8),
    )

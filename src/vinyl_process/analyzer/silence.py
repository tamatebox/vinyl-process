"""Silence candidates: quiet stretches that *may* separate tracks."""

from __future__ import annotations

import numpy as np

from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.analyzer.registry import analyzer
from vinyl_process.models.analysis import (
    RmsProfileSection,
    SilenceRegion,
    SilenceSection,
    SurfaceNoiseSection,
)
from vinyl_process.models.common import SectionMeta
from vinyl_process.signal_ops import runs_of_true


@analyzer(
    name="silence",
    version="1.0",
    description="Quiet regions relative to the measured noise floor.",
    requires=("rms_profile", "surface_noise"),
    defaults={"margin_db": 8.0, "min_duration_seconds": 0.5},
)
def analyze_silence(context: AnalyzerContext) -> SilenceSection:
    profile = context.typed_section("rms_profile", RmsProfileSection)
    noise = context.typed_section("surface_noise", SurfaceNoiseSection)

    sample_rate = context.audio.sample_rate
    num_frames = context.audio.num_frames
    values = np.asarray(profile.values_db, dtype=np.float64)
    threshold_db = noise.noise_floor_db + context.number("margin_db")
    hop_samples = round(profile.hop_seconds * sample_rate)
    window_samples = round(profile.window_seconds * sample_rate)
    min_frames = max(1, round(context.number("min_duration_seconds") / profile.hop_seconds))

    regions: list[SilenceRegion] = []
    for first, last in runs_of_true(values <= threshold_db):
        if last - first < min_frames:
            continue
        segment = values[first:last]
        # A run that touches frame 0 or the final frame extends to the very edge
        # of the file: clamping it there is what makes lead-in / lead-out
        # detection reliable instead of "nearly the end".
        start_sample = 0 if first == 0 else first * hop_samples
        end_sample = (
            num_frames
            if last >= values.size
            else min(num_frames, (last - 1) * hop_samples + window_samples)
        )
        duration_seconds = (end_sample - start_sample) / sample_rate
        depth_db = threshold_db - float(np.mean(segment))
        confidence = float(
            np.clip(
                0.4
                + 0.3 * min(duration_seconds / 2.0, 1.0)
                + 0.3 * min(max(depth_db, 0.0) / 6.0, 1.0),
                0.0,
                1.0,
            )
        )
        regions.append(
            SilenceRegion(
                start_sample=start_sample,
                end_sample=end_sample,
                mean_rms_db=round(float(np.mean(segment)), 2),
                duration_seconds=round(duration_seconds, 3),
                confidence=round(confidence, 2),
            )
        )

    return SilenceSection(
        meta=SectionMeta(confidence=noise.meta.confidence),
        threshold_db=round(threshold_db, 2),
        regions=regions,
    )

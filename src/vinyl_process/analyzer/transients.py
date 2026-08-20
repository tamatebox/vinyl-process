"""Transient density — how percussive the material is.

The Declick skill needs this: the same threshold that removes clicks from a
sustained string quartet will chew the attacks off a drum kit.
"""

from __future__ import annotations

import numpy as np

from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.analyzer.registry import analyzer
from vinyl_process.models.analysis import TransientsSection
from vinyl_process.models.common import SectionMeta
from vinyl_process.signal_ops import transient_onsets


@analyzer(
    name="transients",
    version="1.0",
    description="Onset density per second.",
    defaults={"hop_seconds": 0.01, "threshold_mad": 6.0, "min_rise_db": 3.0},
)
def analyze_transients(context: AnalyzerContext) -> TransientsSection:
    audio = context.audio
    hop_seconds = context.number("hop_seconds")
    frames = transient_onsets(
        audio.mono(),
        audio.sample_rate,
        hop_seconds=hop_seconds,
        threshold_mad=context.number("threshold_mad"),
        min_rise_db=context.number("min_rise_db"),
    )

    seconds = max(1, int(np.ceil(audio.duration_seconds)))
    density = np.zeros(seconds, dtype=np.float64)
    for frame in frames:
        index = min(seconds - 1, int(frame * hop_seconds))
        density[index] += 1.0

    return TransientsSection(
        meta=SectionMeta(confidence=0.7),
        hop_seconds=hop_seconds,
        density_per_second=[float(v) for v in density],
        mean_per_second=round(float(density.mean()), 3),
        peak_per_second=round(float(density.max()), 3),
    )

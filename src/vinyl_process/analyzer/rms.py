"""Windowed RMS profile — the envelope every level-based detector builds on."""

from __future__ import annotations

import numpy as np

from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.analyzer.registry import analyzer
from vinyl_process.models.analysis import RmsProfileSection
from vinyl_process.models.common import SectionMeta
from vinyl_process.signal_ops import amplitude_to_db, windowed_rms


@analyzer(
    name="rms_profile",
    version="1.0",
    description="Windowed RMS envelope in dBFS.",
    defaults={"window_seconds": 0.2, "hop_seconds": 0.1},
)
def analyze_rms(context: AnalyzerContext) -> RmsProfileSection:
    window_seconds = context.number("window_seconds")
    hop_seconds = context.number("hop_seconds")
    values = windowed_rms(
        context.audio.mono(), context.audio.sample_rate, window_seconds, hop_seconds
    )
    return RmsProfileSection(
        meta=SectionMeta(confidence=1.0),
        window_seconds=window_seconds,
        hop_seconds=hop_seconds,
        values_db=[round(float(v), 2) for v in np.asarray(amplitude_to_db(values))],
    )


def frame_to_sample(section: RmsProfileSection, sample_rate: int, frame: int) -> int:
    """Start sample of RMS frame ``frame``."""
    return round(frame * section.hop_seconds * sample_rate)

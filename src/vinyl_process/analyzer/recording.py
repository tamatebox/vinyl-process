"""Recording information: what the capture chain produced, electrically."""

from __future__ import annotations

import numpy as np

from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.analyzer.registry import analyzer
from vinyl_process.models.analysis import RecordingInfoSection
from vinyl_process.models.common import SectionMeta
from vinyl_process.signal_ops import EPS, amplitude_to_db


@analyzer(
    name="recording_info",
    version="1.0",
    description="Format, DC offset, per-channel level and stereo correlation.",
)
def analyze_recording_info(context: AnalyzerContext) -> RecordingInfoSection:
    samples = context.audio.samples
    dc_offset = samples.mean(axis=0)
    peaks = np.abs(samples).max(axis=0)
    rms = np.sqrt((samples**2).mean(axis=0) + EPS)

    balance_db: float | None = None
    correlation: float | None = None
    if context.audio.num_channels == 2:
        left, right = samples[:, 0], samples[:, 1]
        balance_db = float(amplitude_to_db(rms[0]) - amplitude_to_db(rms[1]))
        if left.std() > EPS and right.std() > EPS:
            correlation = float(np.corrcoef(left, right)[0, 1])

    return RecordingInfoSection(
        meta=SectionMeta(confidence=1.0),
        subtype=context.format.subtype,
        bit_depth=context.format.bit_depth,
        dc_offset=[round(float(v), 8) for v in dc_offset],
        channel_peak_db=[round(float(amplitude_to_db(v)), 2) for v in peaks],
        channel_rms_db=[round(float(amplitude_to_db(v)), 2) for v in rms],
        channel_balance_db=None if balance_db is None else round(balance_db, 2),
        channel_correlation=None if correlation is None else round(correlation, 4),
    )

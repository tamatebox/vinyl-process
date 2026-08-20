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
    version="1.1",
    description="Quiet regions, and where the music before each one stopped.",
    requires=("rms_profile", "surface_noise"),
    defaults={
        "margin_db": 8.0,
        "min_duration_seconds": 0.5,
        "settle_seconds": 1.0,
        "settle_margin_db": 3.0,
    },
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
    settle_frames = max(1, round(context.number("settle_seconds") / profile.hop_seconds))
    settle_margin_db = context.number("settle_margin_db")
    smoothed = _smooth(values, settle_frames)

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
                music_end_sample=(
                    0
                    if start_sample == 0
                    else _music_end(smoothed, first, last, settle_margin_db, hop_samples)
                ),
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


def _smooth(values: np.ndarray, frames: int) -> np.ndarray:
    """Moving average over ``frames``, same length as the input."""
    if frames <= 1:
        return values
    return np.convolve(values, np.ones(frames) / frames, mode="same")


def _music_end(
    smoothed: np.ndarray,
    first_frame: int,
    last_frame: int,
    settle_margin_db: float,
    hop_samples: int,
) -> int:
    """First sample at which the level has settled to this region's own floor.

    ``start_sample`` marks a crossing of a fixed threshold, which for a track that
    fades out happens mid-fade — 4 s early on one track of a tested pressing and
    22 s early on another. What is wanted instead is where the decay flattens out.

    The test runs on a *smoothed* envelope, because a fade flickers by several dB
    and a frame-by-frame comparison stops on the first dip. The reference is the
    region's own quietest smoothed level plus ``settle_margin_db``: in a region
    that is genuinely silent that level is reached at once, and in one that begins
    mid-fade it is where the fade has come down to the floor it settles on.

    Two alternatives were measured on real pressings and rejected: a low
    percentile of the region overshoots a long silent gap by several seconds
    (it waits for a downward fluctuation), and stopping where the envelope stops
    *declining* cut 3 s off a real decay. Erring long is the safe direction —
    faded surface noise is inaudible, a clipped fade is not recoverable.
    """
    segment = smoothed[first_frame:last_frame]
    if segment.size == 0:
        return int(first_frame * hop_samples)
    reference = float(np.min(segment)) + settle_margin_db

    for index in range(first_frame, last_frame):
        if float(smoothed[index]) <= reference:
            return int(index * hop_samples)
    # The whole region is still decaying: err long, because faded noise is
    # inaudible while a clipped fade is not recoverable.
    return int(last_frame * hop_samples)

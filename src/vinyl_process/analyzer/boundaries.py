"""Multi-method track-boundary candidates.

Each detector contributes candidates independently and says how much it trusts
them. Choosing the final boundary set is the Split *skill's* job — treating it
as an optimisation over all the evidence — so nothing here ranks or filters
candidates into a track list.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import argrelmin

from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.analyzer.registry import analyzer
from vinyl_process.analyzer.spectral import compute_spectrum, spectral_flux
from vinyl_process.models.analysis import (
    BoundariesSection,
    BoundaryCandidate,
    RmsProfileSection,
    SilenceRegion,
    SilenceSection,
)
from vinyl_process.models.common import SectionMeta


@analyzer(
    name="boundaries",
    version="1.0",
    description="Candidate cut points from silence, RMS valleys and spectral change.",
    requires=("rms_profile", "silence"),
    defaults={
        "valley_depth_db": 12.0,
        "valley_order": 10,
        "smoothing_frames": 5,
        "spectral_nperseg": 4096,
        "spectral_top_n": 20,
        "spectral_min_z": 4.0,
        "spectral_min_separation_seconds": 0.5,
    },
)
def analyze_boundaries(context: AnalyzerContext) -> BoundariesSection:
    profile = context.typed_section("rms_profile", RmsProfileSection)
    silence = context.typed_section("silence", SilenceSection)
    num_frames = context.audio.num_frames
    sample_rate = context.audio.sample_rate

    candidates = [
        *_from_silence(silence.regions, num_frames),
        *_from_rms_valleys(context, profile, sample_rate),
        *_from_spectral_change(context),
    ]
    candidates.sort(key=lambda candidate: (candidate.sample, candidate.method))
    lead_in_end, lead_out_start = _playable_region(silence.regions, num_frames)

    return BoundariesSection(
        meta=SectionMeta(confidence=silence.meta.confidence),
        candidates=candidates,
        lead_in_end_sample=lead_in_end,
        lead_out_start_sample=lead_out_start,
    )


def _from_silence(regions: list[SilenceRegion], num_frames: int) -> list[BoundaryCandidate]:
    """Midpoint of each interior silence; edge regions are lead-in / lead-out."""
    return [
        BoundaryCandidate(
            sample=(region.start_sample + region.end_sample) // 2,
            method="silence",
            confidence=region.confidence,
        )
        for region in regions
        if region.start_sample > 0 and region.end_sample < num_frames
    ]


def _from_rms_valleys(
    context: AnalyzerContext, profile: RmsProfileSection, sample_rate: int
) -> list[BoundaryCandidate]:
    """Local minima deep enough to be a gap rather than a quiet passage."""
    values = np.asarray(profile.values_db, dtype=np.float64)
    smoothing = context.integer("smoothing_frames")
    if values.size < max(5, smoothing):
        return []
    kernel = np.ones(smoothing) / smoothing
    smoothed = np.convolve(values, kernel, mode="same")
    loud_level = float(np.percentile(smoothed, 90))
    hop_samples = round(profile.hop_seconds * sample_rate)
    depth_threshold = context.number("valley_depth_db")

    candidates = []
    for index in argrelmin(smoothed, order=context.integer("valley_order"))[0]:
        depth = loud_level - float(smoothed[index])
        if depth < depth_threshold:
            continue
        confidence = float(np.clip(0.3 + 0.5 * min(depth / 30.0, 1.0), 0.0, 0.9))
        candidates.append(
            BoundaryCandidate(
                sample=int(index * hop_samples),
                method="rms_valley",
                confidence=round(confidence, 2),
            )
        )
    return candidates


def _from_spectral_change(context: AnalyzerContext) -> list[BoundaryCandidate]:
    """Frames with unusually strong spectral flux — weak supporting evidence."""
    magnitude, _freqs, hop = compute_spectrum(context.audio, context.integer("spectral_nperseg"))
    flux = spectral_flux(magnitude)
    if flux.size == 0:
        return []
    median = float(np.median(flux))
    mad = float(np.median(np.abs(flux - median))) or 1e-9
    z_scores = (flux - median) / (1.4826 * mad)
    minimum_z = context.number("spectral_min_z")

    # One musical transition produces a burst of high-flux frames. Reporting all
    # of them would bury the Split skill in near-duplicates, so each cluster is
    # represented by its strongest frame. This is de-duplication of one
    # measurement, not a judgement about which boundary is right.
    minimum_separation = round(
        context.number("spectral_min_separation_seconds") * context.audio.sample_rate / hop
    )
    chosen: list[int] = []
    for index in np.argsort(z_scores)[::-1][: context.integer("spectral_top_n")]:
        z = float(z_scores[index])
        if z < minimum_z:
            break
        if any(abs(int(index) - other) < minimum_separation for other in chosen):
            continue
        chosen.append(int(index))

    return [
        BoundaryCandidate(
            sample=int(index * hop),
            method="spectral_change",
            confidence=round(
                float(np.clip(0.2 + 0.05 * min(float(z_scores[index]), 8.0), 0.0, 0.6)), 2
            ),
        )
        for index in sorted(chosen)
    ]


def _playable_region(
    regions: list[SilenceRegion], num_frames: int
) -> tuple[int | None, int | None]:
    """End of the leading silence and start of the trailing one, if present.

    For a whole-side recording the trailing silence is the run-out groove.
    """
    lead_in_end = next((r.end_sample for r in regions if r.start_sample == 0), None)
    lead_out_start = next(
        (r.start_sample for r in reversed(regions) if r.end_sample >= num_frames), None
    )
    return lead_in_end, lead_out_start

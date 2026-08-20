"""Per-band level over time — which part of the spectrum carries the energy.

The measurement `rms_profile` cannot make: it sums the bands, so whichever band
the surface is loudest in sets the broadband level and an entrance elsewhere in
the spectrum does not move it. `spectral` has the frequency axis but averages the
whole file. This has both.

**Read a step in one band while its neighbours hold still, not the tilt of the
spectrum.** The tilt is not a constant of surface noise, and assuming one was
wrong here first time round. Unequalised groove noise rises about 3 dB/octave,
but RIAA playback then boosts the bass and cuts the treble, so the *continuous*
part comes out weighted towards the low end — measured on the 12" this was
written for, a clean run-out falls monotonically from -71 dBFS in 40-150 Hz to
-93 dBFS in 3-8 kHz. *Impulsive* damage does not: abrasion is broadband, and a
scuffed lead-in on that same side reads -72 dBFS in the top band, 20 dB above
the run-out there. So "surface is bright" describes a scuffed groove against a
clean one, not surface noise as such — while a step in one band is the same
evidence either way.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np

from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.analyzer.registry import analyzer
from vinyl_process.models.analysis import BandLevels, BandProfileSection
from vinyl_process.models.common import SectionMeta
from vinyl_process.signal_ops import EPS, amplitude_to_db

_FRAME_CHUNK = 512
"""Frames per FFT batch. Bounds peak memory on a 13-minute side."""


def _band_mean_square(
    mono: np.ndarray,
    window: int,
    hop: int,
    edges: np.ndarray,
    sample_rate: int,
) -> np.ndarray:
    """Mean square per ``(band, frame)``, hop-aligned to sample 0.

    A Hann-windowed periodogram per frame, summed over each band's bins and
    compensated for the window, so the bands of one frame sum to that frame's
    total mean square (Parseval).
    """
    starts = np.arange(0, len(mono) - window + 1, hop)
    taper = np.hanning(window)
    correction = window**2 * float(np.mean(taper**2))
    frequencies = np.fft.rfftfreq(window, 1.0 / sample_rate)
    # Both-sided power from a one-sided spectrum: every bin but DC and Nyquist
    # stands for two.
    doubling = np.full(frequencies.size, 2.0)
    doubling[0] = 1.0
    if window % 2 == 0:
        doubling[-1] = 1.0

    masks = [(frequencies >= low) & (frequencies < high) for low, high in pairwise(edges)]
    out = np.empty((len(masks), starts.size), dtype=np.float64)
    for offset in range(0, starts.size, _FRAME_CHUNK):
        batch = starts[offset : offset + _FRAME_CHUNK]
        frames = np.lib.stride_tricks.sliding_window_view(mono, window)[batch] * taper
        power = np.abs(np.fft.rfft(frames, axis=1)) ** 2 * doubling / correction
        for index, mask in enumerate(masks):
            out[index, offset : offset + batch.size] = power[:, mask].sum(axis=1)
    return out


@analyzer(
    name="band_profile",
    version="1.0",
    description="Windowed RMS per frequency band, with each band's own floor.",
    defaults={
        "window_seconds": 0.2,
        "hop_seconds": 0.2,
        "band_edges_hz": [40.0, 150.0, 400.0, 1000.0, 3000.0, 8000.0],
        "floor_percentile": 10.0,
    },
)
def analyze_band_profile(context: AnalyzerContext) -> BandProfileSection:
    sample_rate = context.audio.sample_rate
    window_seconds = context.number("window_seconds")
    hop_seconds = context.number("hop_seconds")
    percentile = context.number("floor_percentile")

    nyquist = sample_rate / 2.0
    requested = sorted(context.numbers("band_edges_hz"))
    # Clamp the top edge rather than dropping the band it belongs to; a band
    # whose *lower* edge is past Nyquist has nothing to measure and is omitted.
    edges = np.array([edge for edge in requested if edge < nyquist] + [min(requested[-1], nyquist)])
    edges = np.unique(edges)

    mono = context.audio.mono()
    window = max(8, round(window_seconds * sample_rate))
    hop = max(1, round(hop_seconds * sample_rate))
    if edges.size < 2 or mono.size < window:
        return BandProfileSection(
            meta=SectionMeta(confidence=1.0),
            window_seconds=window_seconds,
            hop_seconds=hop_seconds,
            bands=[],
        )

    mean_square = _band_mean_square(mono, window, hop, edges, sample_rate)
    bands: list[BandLevels] = []
    for index, (low, high) in enumerate(pairwise(edges)):
        values = np.asarray(amplitude_to_db(np.sqrt(mean_square[index] + EPS)))
        bands.append(
            BandLevels(
                low_hz=float(low),
                high_hz=float(high),
                floor_db=round(float(np.percentile(values, percentile)), 2),
                values_db=[round(float(value), 2) for value in values],
            )
        )
    return BandProfileSection(
        meta=SectionMeta(confidence=1.0),
        window_seconds=window_seconds,
        hop_seconds=hop_seconds,
        bands=bands,
    )

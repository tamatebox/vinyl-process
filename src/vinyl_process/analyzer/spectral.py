"""Spectral features, plus the STFT helpers other analyzers reuse."""

from __future__ import annotations

import numpy as np
from scipy.signal import stft

from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.analyzer.registry import analyzer
from vinyl_process.audio import AudioBuffer
from vinyl_process.models.analysis import BandEnergy, SpectralSection
from vinyl_process.models.common import SectionMeta
from vinyl_process.signal_ops import EPS, amplitude_to_db

#: Roughly octave-wide bands: rumble, bass, mids, presence, hiss.
DEFAULT_BANDS_HZ: tuple[tuple[float, float], ...] = (
    (0.0, 40.0),
    (40.0, 160.0),
    (160.0, 640.0),
    (640.0, 2560.0),
    (2560.0, 10240.0),
    (10240.0, 24000.0),
)


def compute_spectrum(audio: AudioBuffer, nperseg: int = 4096) -> tuple[np.ndarray, np.ndarray, int]:
    """Magnitude spectrogram ``(freqs, frames)``, the frequency axis, the hop."""
    nperseg = min(nperseg, max(8, audio.num_frames))
    hop = max(1, nperseg // 2)
    freqs, _times, zxx = stft(
        audio.mono(), fs=audio.sample_rate, nperseg=nperseg, noverlap=nperseg - hop
    )
    return np.abs(zxx), freqs, hop


def spectral_flux(magnitude: np.ndarray) -> np.ndarray:
    """Positive spectral change per frame — onset / boundary evidence."""
    if magnitude.shape[1] < 2:
        return np.zeros(0)
    return np.asarray(np.maximum(np.diff(magnitude, axis=1), 0.0).sum(axis=0), dtype=np.float64)


@analyzer(
    name="spectral",
    version="1.0",
    description="Centroid, roll-off, rumble, hiss and band energies.",
    defaults={
        "nperseg": 4096,
        "rumble_max_hz": 40.0,
        "hiss_min_hz": 12000.0,
        "rolloff_fraction": 0.85,
    },
)
def analyze_spectral(context: AnalyzerContext) -> SpectralSection:
    magnitude, freqs, _hop = compute_spectrum(context.audio, context.integer("nperseg"))
    power = magnitude**2
    frame_power = power.sum(axis=0) + EPS
    centroids = (freqs[:, None] * power).sum(axis=0) / frame_power

    cumulative = np.cumsum(power, axis=0) / frame_power
    rolloff = freqs[np.argmax(cumulative >= context.number("rolloff_fraction"), axis=0)]

    total = float(power.sum()) + EPS
    rumble = float(power[freqs <= context.number("rumble_max_hz")].sum())
    hiss = float(power[freqs >= context.number("hiss_min_hz")].sum())

    nyquist = context.audio.sample_rate / 2.0
    bands = [
        BandEnergy(
            low_hz=low,
            high_hz=min(high, nyquist),
            energy_db=round(
                float(
                    amplitude_to_db(
                        np.sqrt(float(power[(freqs >= low) & (freqs < high)].sum()) / total)
                    )
                ),
                2,
            ),
        )
        for low, high in DEFAULT_BANDS_HZ
        if low < nyquist
    ]

    return SpectralSection(
        meta=SectionMeta(confidence=1.0),
        centroid_mean_hz=round(float(centroids.mean()), 1),
        centroid_std_hz=round(float(centroids.std()), 1),
        rolloff_mean_hz=round(float(rolloff.mean()), 1),
        rumble_db=round(float(amplitude_to_db(np.sqrt(rumble / total))), 2),
        hiss_db=round(float(amplitude_to_db(np.sqrt(hiss / total))), 2),
        bands=bands,
    )

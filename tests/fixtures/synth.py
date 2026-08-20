"""Synthesised vinyl-like recordings with known ground truth.

The repository contains no audio files. Every fixture is generated from a fixed
seed, so each expected value (gap positions, click count, peak level) is known by
construction and the tests can assert on measurement *accuracy*, not just shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

DEFAULT_SAMPLE_RATE = 44100
SURFACE_NOISE_AMPLITUDE = 4e-4
CLICK_AMPLITUDE = 0.45
CLICK_WIDTH_SAMPLES = 3


@dataclass(frozen=True)
class SyntheticRecording:
    """A generated recording plus the truth used to build it."""

    path: Path
    sample_rate: int
    num_frames: int
    programme: tuple[tuple[float, float], ...]
    """``(start, end)`` in seconds of each musical passage."""

    gaps: tuple[tuple[float, float], ...]
    """``(start, end)`` in seconds of each silent stretch, including the edges."""

    level_scales: tuple[float, ...]
    """Amplitude scale applied to each passage, so level tests know the truth."""

    click_positions: tuple[int, ...]
    peak_amplitude: float

    def samples(self, seconds: float) -> int:
        return round(seconds * self.sample_rate)

    @property
    def lead_in_end(self) -> float:
        return self.gaps[0][1]

    @property
    def lead_out_start(self) -> float:
        return self.gaps[-1][0]

    @property
    def interior_gaps(self) -> tuple[tuple[float, float], ...]:
        return self.gaps[1:-1]


def _tone(seconds: float, frequency: float, sample_rate: int) -> np.ndarray:
    t = np.arange(round(seconds * sample_rate)) / sample_rate
    envelope = np.minimum(1.0, np.minimum(t / 0.05, (seconds - t) / 0.05))
    return (
        0.45 * np.sin(2.0 * np.pi * frequency * t)
        + 0.20 * np.sin(2.0 * np.pi * frequency * 2.5 * t)
    ) * envelope


def write_recording(
    path: Path,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    lead_in: float = 2.0,
    track_seconds: tuple[float, ...] = (8.0, 7.0),
    gap: float = 2.2,
    lead_out: float = 2.5,
    frequencies: tuple[float, ...] = (220.0, 294.0),
    level_scales: tuple[float, ...] = (1.0,),
    click_times: tuple[float, ...] = (3.3, 5.1, 7.9, 14.2, 16.05),
    subtype: str = "PCM_24",
    seed: int = 11,
) -> SyntheticRecording:
    """Write a lead-in / tracks / lead-out recording with injected clicks."""
    rng = np.random.default_rng(seed)

    def noise(seconds: float) -> np.ndarray:
        return rng.normal(0.0, SURFACE_NOISE_AMPLITUDE, round(seconds * sample_rate))

    blocks: list[np.ndarray] = [noise(lead_in)]
    programme: list[tuple[float, float]] = []
    gaps: list[tuple[float, float]] = [(0.0, lead_in)]
    cursor = lead_in

    for index, seconds in enumerate(track_seconds):
        scale = level_scales[index % len(level_scales)]
        blocks.append(_tone(seconds, frequencies[index % len(frequencies)], sample_rate) * scale)
        programme.append((cursor, cursor + seconds))
        cursor += seconds
        is_last = index == len(track_seconds) - 1
        pause = lead_out if is_last else gap
        blocks.append(noise(pause))
        gaps.append((cursor, cursor + pause))
        cursor += pause

    mono = np.concatenate(blocks)
    positions = []
    for click_time in click_times:
        position = round(click_time * sample_rate)
        if 0 <= position < len(mono) - CLICK_WIDTH_SAMPLES:
            mono[position : position + CLICK_WIDTH_SAMPLES] += CLICK_AMPLITUDE
            positions.append(position)

    # A real cutter never delivers perfectly matched channels.
    stereo = np.column_stack([mono, mono * 0.985])
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), stereo, sample_rate, subtype=subtype)

    return SyntheticRecording(
        path=path,
        sample_rate=sample_rate,
        num_frames=len(mono),
        programme=tuple(programme),
        gaps=tuple(gaps),
        level_scales=tuple(
            level_scales[index % len(level_scales)] for index in range(len(track_seconds))
        ),
        click_positions=tuple(positions),
        peak_amplitude=float(np.max(np.abs(stereo))),
    )

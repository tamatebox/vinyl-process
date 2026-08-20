"""Audio I/O and the in-memory audio type shared by the analyzer and DSP.

Everything is float64 internally. Conversion to the export bit depth happens
exactly once, in :func:`save_audio`, which is also the only place dither is
ever applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import soundfile as sf

from vinyl_process.errors import AudioIOError
from vinyl_process.hashing import digest_file
from vinyl_process.models.common import SourceInfo

DitherType = Literal["none", "tpdf"]

#: (container format, bit depth) -> libsndfile subtype.
_SUBTYPES: dict[tuple[str, int], str] = {
    ("flac", 16): "PCM_16",
    ("flac", 24): "PCM_24",
    ("wav", 16): "PCM_16",
    ("wav", 24): "PCM_24",
    ("aiff", 16): "PCM_16",
    ("aiff", 24): "PCM_24",
}

#: libsndfile subtype -> nominal bit depth, for reporting only.
_SUBTYPE_BITS: dict[str, int] = {
    "PCM_S8": 8,
    "PCM_U8": 8,
    "PCM_16": 16,
    "PCM_24": 24,
    "PCM_32": 32,
    "FLOAT": 32,
    "DOUBLE": 64,
}


@dataclass(frozen=True)
class AudioBuffer:
    """Immutable audio: samples shaped ``(num_frames, num_channels)``, float64."""

    samples: np.ndarray
    sample_rate: int

    def __post_init__(self) -> None:
        if self.samples.ndim != 2:
            raise ValueError("samples must be shaped (num_frames, num_channels)")
        if self.samples.dtype != np.float64:
            raise ValueError(f"samples must be float64, got {self.samples.dtype}")
        if self.sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {self.sample_rate}")

    @property
    def num_frames(self) -> int:
        return int(self.samples.shape[0])

    @property
    def num_channels(self) -> int:
        return int(self.samples.shape[1])

    @property
    def duration_seconds(self) -> float:
        return self.num_frames / self.sample_rate

    def slice(self, start_sample: int, end_sample: int) -> AudioBuffer:
        """Sample-exact cut, ``[start_sample, end_sample)``."""
        if not 0 <= start_sample < end_sample <= self.num_frames:
            raise ValueError(
                f"slice [{start_sample}, {end_sample}) out of range 0..{self.num_frames}"
            )
        return AudioBuffer(self.samples[start_sample:end_sample].copy(), self.sample_rate)

    def with_samples(self, samples: np.ndarray) -> AudioBuffer:
        """Same sample rate, new sample block (keeps engines terse)."""
        return AudioBuffer(np.ascontiguousarray(samples, dtype=np.float64), self.sample_rate)

    def mono(self) -> np.ndarray:
        """Channel mean, shaped ``(num_frames,)``. For measurement only."""
        return np.asarray(self.samples.mean(axis=1), dtype=np.float64)


def load_audio(path: str | Path) -> AudioBuffer:
    """Read any libsndfile-supported file as float64."""
    try:
        samples, sample_rate = sf.read(str(path), dtype="float64", always_2d=True)
    except (RuntimeError, sf.LibsndfileError, OSError) as exc:
        raise AudioIOError(f"cannot read audio from {path}: {exc}") from exc
    return AudioBuffer(np.ascontiguousarray(samples, dtype=np.float64), int(sample_rate))


def save_audio(
    path: str | Path,
    audio: AudioBuffer,
    audio_format: str,
    bit_depth: int,
    *,
    dither: DitherType = "none",
    dither_seed: int = 0,
) -> None:
    """Write ``audio``, converting to ``bit_depth`` exactly once.

    TPDF dither is generated from ``dither_seed`` through numpy's PCG64 stream,
    whose output is stable across numpy versions — so a dithered export is still
    bit-reproducible.
    """
    subtype = _SUBTYPES.get((audio_format.lower(), bit_depth))
    if subtype is None:
        raise AudioIOError(f"unsupported export target: {audio_format}/{bit_depth}-bit")

    samples = audio.samples
    if dither == "tpdf":
        samples = _apply_tpdf_dither(samples, bit_depth, dither_seed)
    samples = np.clip(samples, -1.0, 1.0)

    try:
        sf.write(
            str(path),
            samples,
            audio.sample_rate,
            subtype=subtype,
            format=audio_format.upper(),
        )
    except (RuntimeError, sf.LibsndfileError, OSError) as exc:
        raise AudioIOError(f"cannot write audio to {path}: {exc}") from exc


def _apply_tpdf_dither(samples: np.ndarray, bit_depth: int, seed: int) -> np.ndarray:
    """Add triangular-PDF noise of +/-1 LSB peak before quantisation."""
    lsb = 2.0 ** -(bit_depth - 1)
    rng = np.random.default_rng(seed)
    noise = (rng.random(samples.shape) - rng.random(samples.shape)) * lsb
    return np.asarray(samples + noise, dtype=np.float64)


def save_audio_float64(path: str | Path, audio: AudioBuffer) -> None:
    """Write a lossless float64 WAV — used for engine round-trips, never export."""
    try:
        sf.write(str(path), audio.samples, audio.sample_rate, subtype="DOUBLE", format="WAV")
    except (RuntimeError, sf.LibsndfileError, OSError) as exc:
        raise AudioIOError(f"cannot write audio to {path}: {exc}") from exc


@dataclass(frozen=True)
class FormatInfo:
    """What the container says about itself, for ``recording_info``."""

    subtype: str
    bit_depth: int | None


def format_info(path: str | Path) -> FormatInfo:
    info = _sf_info(path)
    return FormatInfo(subtype=str(info.subtype), bit_depth=_SUBTYPE_BITS.get(str(info.subtype)))


def source_info_for(path: str | Path) -> SourceInfo:
    """Build the :class:`SourceInfo` that anchors every document to this file."""
    info = _sf_info(path)
    if info.samplerate <= 0:
        raise AudioIOError(f"{path}: invalid sample rate {info.samplerate}")
    return SourceInfo(
        path=str(path),
        sha256=digest_file(path),
        sample_rate=int(info.samplerate),
        channels=int(info.channels),
        num_samples=int(info.frames),
        duration_seconds=float(info.frames) / float(info.samplerate),
    )


def _sf_info(path: str | Path) -> sf._SoundFileInfo:
    try:
        return sf.info(str(path))
    except (RuntimeError, sf.LibsndfileError, OSError) as exc:
        raise AudioIOError(f"cannot inspect audio file {path}: {exc}") from exc

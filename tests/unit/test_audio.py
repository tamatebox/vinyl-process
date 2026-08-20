"""Audio I/O: the one place where bit depth conversion and dither happen."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vinyl_process.audio import (
    AudioBuffer,
    format_info,
    load_audio,
    save_audio,
    source_info_for,
)
from vinyl_process.errors import AudioIOError
from vinyl_process.hashing import digest_file

SAMPLE_RATE = 44100


def buffer(seconds: float = 1.0, amplitude: float = 0.5) -> AudioBuffer:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    tone = amplitude * np.sin(2 * np.pi * 440 * t)
    return AudioBuffer(np.column_stack([tone, tone]), SAMPLE_RATE)


def test_buffer_rejects_wrong_shape_and_dtype() -> None:
    with pytest.raises(ValueError, match="num_frames, num_channels"):
        AudioBuffer(np.zeros(10), SAMPLE_RATE)
    with pytest.raises(ValueError, match="float64"):
        AudioBuffer(np.zeros((10, 2), dtype=np.float32), SAMPLE_RATE)
    with pytest.raises(ValueError, match="sample_rate"):
        AudioBuffer(np.zeros((10, 2)), 0)


def test_slice_is_sample_exact_and_copies() -> None:
    audio = buffer()
    piece = audio.slice(100, 200)
    assert piece.num_frames == 100
    assert np.array_equal(piece.samples, audio.samples[100:200])
    piece.samples[0, 0] = 99.0
    assert audio.samples[100, 0] != 99.0
    with pytest.raises(ValueError, match="out of range"):
        audio.slice(0, audio.num_frames + 1)


def test_mono_is_the_channel_mean() -> None:
    audio = AudioBuffer(np.column_stack([np.full(10, 1.0), np.full(10, 0.0)]), SAMPLE_RATE)
    assert np.allclose(audio.mono(), 0.5)


@pytest.mark.parametrize(("audio_format", "bit_depth"), [("flac", 24), ("wav", 16), ("aiff", 24)])
def test_round_trip_through_every_export_target(
    tmp_path: Path, audio_format: str, bit_depth: int
) -> None:
    path = tmp_path / f"out.{audio_format}"
    original = buffer()
    save_audio(path, original, audio_format, bit_depth)
    reloaded = load_audio(path)

    assert reloaded.sample_rate == original.sample_rate
    assert reloaded.num_frames == original.num_frames
    tolerance = 2.0 ** -(bit_depth - 2)
    assert np.max(np.abs(reloaded.samples - original.samples)) < tolerance
    assert format_info(path).bit_depth == bit_depth


def test_unsupported_export_target_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AudioIOError, match="unsupported export target"):
        save_audio(tmp_path / "x.flac", buffer(), "flac", 8)


def test_missing_file_raises_audio_io_error(tmp_path: Path) -> None:
    with pytest.raises(AudioIOError):
        load_audio(tmp_path / "nope.wav")
    with pytest.raises(AudioIOError):
        source_info_for(tmp_path / "nope.wav")


def test_source_info_matches_the_file(tmp_path: Path) -> None:
    path = tmp_path / "src.wav"
    save_audio(path, buffer(2.0), "wav", 24)
    info = source_info_for(path)
    assert info.sample_rate == SAMPLE_RATE
    assert info.channels == 2
    assert info.num_samples == 2 * SAMPLE_RATE
    assert info.duration_seconds == pytest.approx(2.0)
    assert info.sha256 == digest_file(path)


def test_dither_is_seeded_and_reproducible(tmp_path: Path) -> None:
    audio = buffer(0.2, amplitude=0.001)
    digests = []
    for name, seed in [("a", 7), ("b", 7), ("c", 8)]:
        path = tmp_path / f"{name}.wav"
        save_audio(path, audio, "wav", 16, dither="tpdf", dither_seed=seed)
        digests.append(digest_file(path))

    assert digests[0] == digests[1], "same seed must produce identical bytes"
    assert digests[0] != digests[2], "a different seed must re-roll the noise"

    plain = tmp_path / "plain.wav"
    save_audio(plain, audio, "wav", 16)
    assert digest_file(plain) != digests[0]


def test_export_clips_instead_of_wrapping(tmp_path: Path) -> None:
    loud = AudioBuffer(np.full((100, 2), 1.5), SAMPLE_RATE)
    path = tmp_path / "loud.wav"
    save_audio(path, loud, "wav", 24)
    assert np.max(load_audio(path).samples) <= 1.0

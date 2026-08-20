"""Tag writing across every supported container."""

from __future__ import annotations

from pathlib import Path

import mutagen
import numpy as np
import pytest

from vinyl_process.audio import AudioBuffer, save_audio
from vinyl_process.errors import MetadataError
from vinyl_process.metadata.tagger import apply_tags, resolve_tags
from vinyl_process.models.plan import MetadataPlan

SAMPLE_RATE = 44100

METADATA = MetadataPlan.model_validate(
    {
        "album": "Test Pressing",
        "album_artist": "Synthetic Ensemble",
        "year": 1973,
        "genre": "Electronic",
        "styles": ["Test Tone", "Drone"],
        "label": "Fixture Records",
        "catalog_number": "FIX-001",
        "discogs_release_id": "1873013",
        "musicbrainz_release_id": "mb-123",
        "tracks": [
            {"index": 1, "title": "First", "position": "A1"},
            {"index": 2, "title": "Second", "artist": "Guest", "position": "A2"},
        ],
    }
)


@pytest.fixture
def audio_file(tmp_path: Path) -> Path:
    t = np.arange(SAMPLE_RATE // 10) / SAMPLE_RATE
    tone = 0.2 * np.sin(2 * np.pi * 440 * t)
    buffer = AudioBuffer(np.column_stack([tone, tone]), SAMPLE_RATE)
    path = tmp_path / "track.flac"
    save_audio(path, buffer, "flac", 24)
    return path


def test_resolve_tags_prefers_the_track_artist_then_falls_back() -> None:
    first = resolve_tags(METADATA, 1, 2)
    second = resolve_tags(METADATA, 2, 2)
    assert first["artist"] == ["Synthetic Ensemble"]
    assert second["artist"] == ["Guest"]
    assert first["tracknumber"] == ["1"]
    assert first["tracktotal"] == ["2"]
    assert first["style"] == ["Test Tone", "Drone"]
    assert "musicbrainz_albumid" in first


def test_resolve_tags_omits_empty_values() -> None:
    tags = resolve_tags(MetadataPlan(album="Only"), 1, 1)
    assert tags == {"album": ["Only"], "tracknumber": ["1"], "tracktotal": ["1"]}


def test_flac_tags_are_written(audio_file: Path) -> None:
    apply_tags(audio_file, METADATA, 1, 2)
    tags = mutagen.File(str(audio_file)).tags
    assert tags["album"] == ["Test Pressing"]
    assert tags["title"] == ["First"]
    assert tags["position"] == ["A1"]
    assert tags["style"] == ["Test Tone", "Drone"]


@pytest.mark.parametrize("audio_format", ["wav", "aiff"])
def test_id3_containers_are_tagged(tmp_path: Path, audio_format: str) -> None:
    t = np.arange(SAMPLE_RATE // 10) / SAMPLE_RATE
    tone = 0.2 * np.sin(2 * np.pi * 440 * t)
    path = tmp_path / f"track.{audio_format}"
    save_audio(path, AudioBuffer(np.column_stack([tone, tone]), SAMPLE_RATE), audio_format, 24)

    apply_tags(path, METADATA, 2, 2)
    tags = mutagen.File(str(path)).tags
    assert tags["TALB"].text == ["Test Pressing"]
    assert tags["TIT2"].text == ["Second"]
    assert tags["TPE1"].text == ["Guest"]
    assert tags["TRCK"].text == ["2/2"]
    assert tags["TXXX:VINYL_POSITION"].text == ["A2"]


def test_tagging_is_repeatable_and_replaces_previous_values(audio_file: Path) -> None:
    apply_tags(audio_file, METADATA, 1, 2)
    apply_tags(audio_file, MetadataPlan(album="Replaced"), 1, 1)
    tags = mutagen.File(str(audio_file)).tags
    assert tags["album"] == ["Replaced"]
    assert "title" not in tags


def test_artwork_is_embedded(audio_file: Path, tmp_path: Path) -> None:
    artwork = tmp_path / "cover.png"
    artwork.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    plan = METADATA.model_copy(update={"artwork_path": str(artwork)})

    apply_tags(audio_file, plan, 1, 2)
    pictures = mutagen.File(str(audio_file)).pictures
    assert len(pictures) == 1
    assert pictures[0].mime == "image/png"
    assert pictures[0].type == 3


def test_unsupported_artwork_format_is_rejected(audio_file: Path, tmp_path: Path) -> None:
    artwork = tmp_path / "cover.bmp"
    artwork.write_bytes(b"BM")
    plan = METADATA.model_copy(update={"artwork_path": str(artwork)})
    with pytest.raises(MetadataError, match="unsupported artwork format"):
        apply_tags(audio_file, plan, 1, 2)


def test_missing_artwork_file_is_reported(audio_file: Path, tmp_path: Path) -> None:
    plan = METADATA.model_copy(update={"artwork_path": str(tmp_path / "absent.jpg")})
    with pytest.raises(MetadataError, match="cannot read artwork"):
        apply_tags(audio_file, plan, 1, 2)


def test_unsupported_container_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "track.ogg"
    path.write_bytes(b"not audio")
    with pytest.raises(MetadataError, match="supported containers"):
        apply_tags(path, METADATA, 1, 1)


def test_album_total_overrides_the_per_run_count() -> None:
    """Side B of a record tags 6/10, not 6/5."""
    side_b = MetadataPlan.model_validate(
        {
            "total_tracks": 10,
            "album": "Two Sides",
            "tracks": [{"index": 6, "title": "Sixth"}],
        }
    )
    tags = resolve_tags(side_b, 6, total_tracks=5)
    assert tags["tracknumber"] == ["6"]
    assert tags["tracktotal"] == ["10"]


DOUBLE_ALBUM = MetadataPlan.model_validate(
    {
        "total_tracks": 16,
        "disc_number": 2,
        "total_discs": 2,
        "album": "Two Records",
        "comment": "Vinyl rip. Discogs release 1873013 (FIX-001).",
        "tracks": [{"index": 9, "title": "Ninth", "position": "C1"}],
    }
)


def test_disc_number_and_comment_reach_a_flac(audio_file: Path) -> None:
    apply_tags(audio_file, DOUBLE_ALBUM, 9, 8)
    tags = mutagen.File(str(audio_file)).tags
    assert tags["discnumber"] == ["2"]
    assert tags["disctotal"] == ["2"]
    assert tags["comment"] == ["Vinyl rip. Discogs release 1873013 (FIX-001)."]


def test_disc_number_and_comment_reach_an_id3_container(tmp_path: Path) -> None:
    """TPOS carries "n/m" in one frame and COMM needs a language, so neither
    goes through the plain frame map the other tags use."""
    t = np.arange(SAMPLE_RATE // 10) / SAMPLE_RATE
    tone = 0.2 * np.sin(2 * np.pi * 440 * t)
    path = tmp_path / "track.wav"
    save_audio(path, AudioBuffer(np.column_stack([tone, tone]), SAMPLE_RATE), "wav", 24)

    apply_tags(path, DOUBLE_ALBUM, 9, 8)
    tags = mutagen.File(str(path)).tags
    assert tags["TPOS"].text == ["2/2"]
    assert tags["COMM::eng"].text == ["Vinyl rip. Discogs release 1873013 (FIX-001)."]


def test_a_single_disc_album_carries_no_disc_tags() -> None:
    """The fields are optional, and an absent disc number must stay absent
    rather than become a 1 nobody chose."""
    tags = resolve_tags(MetadataPlan(album="One Record"), 1, 1)
    assert "discnumber" not in tags
    assert "disctotal" not in tags
    assert "comment" not in tags


def test_a_disc_number_without_a_total_is_written_alone() -> None:
    plan = MetadataPlan.model_validate({"disc_number": 1, "tracks": [{"index": 1, "title": "A"}]})
    tags = resolve_tags(plan, 1, 1)
    assert tags["discnumber"] == ["1"]
    assert "disctotal" not in tags

"""Tag writing.

Applied to exported files after all audio processing, and independent of DSP by
design: re-tagging an album must never require re-processing it. Every value
comes from the plan's ``metadata`` section — this module resolves and maps, it
never invents.
"""

from __future__ import annotations

from pathlib import Path

from mutagen.aiff import AIFF
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPUB, TRCK, TXXX
from mutagen.wave import WAVE

from vinyl_process.errors import MetadataError
from vinyl_process.models.plan import MetadataPlan

FLAC_SUFFIXES = frozenset({".flac"})
ID3_SUFFIXES = frozenset({".wav", ".aiff", ".aif"})
SUPPORTED_SUFFIXES = FLAC_SUFFIXES | ID3_SUFFIXES

_IMAGE_MIMES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

#: Canonical tag name -> ID3 frame class. Vorbis comments use the names directly.
_ID3_FRAMES = {
    "album": TALB,
    "artist": TPE1,
    "albumartist": TPE2,
    "title": TIT2,
    "date": TDRC,
    "genre": TCON,
    "label": TPUB,
}
_ID3_TXXX = {
    "catalognumber": "CATALOGNUMBER",
    "discogs_release_id": "DISCOGS_RELEASE_ID",
    "musicbrainz_albumid": "MusicBrainz Album Id",
    "style": "STYLE",
    "position": "VINYL_POSITION",
}


def resolve_tags(plan: MetadataPlan, track_index: int, total_tracks: int) -> dict[str, list[str]]:
    """Flatten the plan's metadata into canonical tag names for one track."""
    track = plan.track_for(track_index)
    values: dict[str, object] = {
        "album": plan.album,
        "albumartist": plan.album_artist,
        "artist": (track.artist if track and track.artist else None)
        or plan.artist
        or plan.album_artist,
        "title": track.title if track else None,
        "date": plan.year,
        "genre": plan.genre,
        "label": plan.label,
        "catalognumber": plan.catalog_number,
        "discogs_release_id": plan.discogs_release_id,
        "musicbrainz_albumid": plan.musicbrainz_release_id,
        "tracknumber": track_index,
        "tracktotal": total_tracks,
        "position": track.position if track else None,
        "style": list(plan.styles) or None,
    }
    tags: dict[str, list[str]] = {}
    for key, value in values.items():
        if value is None or value == "" or value == []:
            continue
        tags[key] = [str(item) for item in value] if isinstance(value, list) else [str(value)]
    return tags


def apply_tags(path: str | Path, plan: MetadataPlan, track_index: int, total_tracks: int) -> None:
    """Write the plan's tags into an already-exported file."""
    path = Path(path)
    suffix = path.suffix.lower()
    tags = resolve_tags(plan, track_index, total_tracks)
    artwork = _load_artwork(plan.artwork_path)

    if suffix in FLAC_SUFFIXES:
        _write_flac(path, tags, artwork)
    elif suffix in ID3_SUFFIXES:
        _write_id3(path, tags, artwork)
    else:
        raise MetadataError(
            f"cannot tag {path.name}: supported containers are "
            f"{', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )


def _write_flac(path: Path, tags: dict[str, list[str]], artwork: tuple[bytes, str] | None) -> None:
    try:
        audio = FLAC(str(path))
    except Exception as exc:  # mutagen raises a variety of container errors
        raise MetadataError(f"cannot open {path} for tagging: {exc}") from exc
    audio.delete()
    audio.clear_pictures()
    for key, values in tags.items():
        audio[key] = values
    if artwork is not None:
        data, mime = artwork
        picture = Picture()
        picture.type = 3  # front cover
        picture.mime = mime
        picture.data = data
        audio.add_picture(picture)
    audio.save()


def _write_id3(path: Path, tags: dict[str, list[str]], artwork: tuple[bytes, str] | None) -> None:
    container = AIFF if path.suffix.lower() in {".aiff", ".aif"} else WAVE
    try:
        audio = container(str(path))
    except Exception as exc:
        raise MetadataError(f"cannot open {path} for tagging: {exc}") from exc
    if audio.tags is None:
        audio.add_tags()
    id3: ID3 | None = audio.tags
    if id3 is None:  # pragma: no cover - add_tags() either succeeds or raises
        raise MetadataError(f"{path.name} does not carry an ID3 tag block")
    id3.clear()

    for key, frame in _ID3_FRAMES.items():
        if key in tags:
            id3.add(frame(encoding=3, text=tags[key]))
    if "tracknumber" in tags:
        total = tags.get("tracktotal", [""])[0]
        number = tags["tracknumber"][0]
        id3.add(TRCK(encoding=3, text=[f"{number}/{total}" if total else number]))
    for key, description in _ID3_TXXX.items():
        if key in tags:
            id3.add(TXXX(encoding=3, desc=description, text=tags[key]))
    if artwork is not None:
        data, mime = artwork
        id3.add(APIC(encoding=3, mime=mime, type=3, desc="front", data=data))
    audio.save()


def _load_artwork(artwork_path: str | None) -> tuple[bytes, str] | None:
    if not artwork_path:
        return None
    path = Path(artwork_path)
    mime = _IMAGE_MIMES.get(path.suffix.lower())
    if mime is None:
        raise MetadataError(
            f"unsupported artwork format {path.suffix!r}; use one of "
            f"{', '.join(sorted(_IMAGE_MIMES))}"
        )
    try:
        return path.read_bytes(), mime
    except OSError as exc:
        raise MetadataError(f"cannot read artwork {path}: {exc}") from exc

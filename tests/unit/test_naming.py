"""File naming: the only place plan metadata becomes a path."""

from __future__ import annotations

import pytest

from vinyl_process.errors import MetadataError
from vinyl_process.metadata.naming import (
    MAX_COMPONENT_LENGTH,
    render_track_filename,
    sanitize_component,
    track_filename,
)
from vinyl_process.models.plan import ProcessingPlan

BASE: dict[str, object] = {
    "source": {
        "path": "a.wav",
        "sha256": "x",
        "sample_rate": 44100,
        "channels": 2,
        "num_samples": 44100,
        "duration_seconds": 1.0,
    },
    "split": {"tracks": [{"index": 1, "start_sample": 0, "end_sample": 44100}]},
    "declick": {},
    "normalize": {},
    "metadata": {"album": "Album", "album_artist": "Artist"},
    "export": {},
}


def make_plan(**overrides: object) -> ProcessingPlan:
    payload = {**BASE}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            payload[key] = {**payload[key], **value}  # type: ignore[dict-item]
        else:
            payload[key] = value
    return ProcessingPlan.model_validate(payload)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Speak to Me", "Speak to Me"),
        ("A/B", "A_B"),
        ('bad: "name"?', "bad_ _name__"),
        ("trailing dots...", "trailing dots"),
        ("   ", "untitled"),
        ("", "untitled"),
    ],
)
def test_sanitize_component(raw: str, expected: str) -> None:
    assert sanitize_component(raw) == expected


def test_sanitize_truncates_long_names() -> None:
    assert len(sanitize_component("x" * 500)) == MAX_COMPONENT_LENGTH


def test_titles_come_from_metadata_and_fall_back_to_a_generic_name() -> None:
    with_title = make_plan(metadata={"tracks": [{"index": 1, "title": "Real Title"}]})
    assert render_track_filename(with_title, 1) == "01 - Real Title"
    assert render_track_filename(make_plan(), 1) == "01 - Track 01"


def test_template_fields_are_all_available() -> None:
    plan = make_plan(
        metadata={
            "album": "Dark Side",
            "album_artist": "Pink Floyd",
            "year": 1973,
            "catalog_number": "SHVL 804",
            "tracks": [{"index": 1, "title": "Time", "position": "B1"}],
        },
        export={
            "track_filename_template": (
                "{album_artist} - {album} ({year}) {position} {index:02d} {title} {catalog_number}"
            )
        },
    )
    assert render_track_filename(plan, 1) == "Pink Floyd - Dark Side (1973) B1 01 Time SHVL 804"


def test_unknown_template_field_lists_the_valid_ones() -> None:
    plan = make_plan(export={"track_filename_template": "{titel}"})
    with pytest.raises(MetadataError, match="unknown field 'titel'"):
        render_track_filename(plan, 1)


def test_malformed_template_is_reported() -> None:
    plan = make_plan(export={"track_filename_template": "{index:d"})
    with pytest.raises(MetadataError, match="malformed"):
        render_track_filename(plan, 1)


def test_track_filename_appends_the_container_extension() -> None:
    assert track_filename(make_plan(export={"format": "aiff"}), 1) == "01 - Track 01.aiff"

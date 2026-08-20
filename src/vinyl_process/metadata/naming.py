"""File naming: turning plan metadata into filesystem-safe names.

Deterministic string work, so it lives on the execution side — but the *template*
is a decision and comes from the plan. Rendering happens twice: once in
``vinyl-process lint`` (so a typo fails before any DSP runs) and once in the
executor.
"""

from __future__ import annotations

import re
import unicodedata

from vinyl_process.errors import MetadataError
from vinyl_process.models.plan import ProcessingPlan

#: Characters no mainstream filesystem accepts, plus control characters.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TRAILING = " ."
MAX_COMPONENT_LENGTH = 120


def sanitize_component(name: str, *, max_length: int = MAX_COMPONENT_LENGTH) -> str:
    """Make ``name`` usable as a single path component on any platform."""
    normalised = unicodedata.normalize("NFC", name)
    cleaned = _UNSAFE.sub("_", normalised).strip().rstrip(_TRAILING)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip().rstrip(_TRAILING)
    return cleaned or "untitled"


def default_title(index: int) -> str:
    return f"Track {index:02d}"


def render_track_filename(plan: ProcessingPlan, index: int) -> str:
    """The filename stem for track ``index`` (no extension).

    Titles come from the metadata section even when tagging is disabled: the plan
    must not carry the same title twice, and a disabled ``metadata`` stage means
    "do not write tags", not "forget the names".
    """
    tag = plan.metadata.track_for(index)
    fields = {
        "index": index,
        "title": tag.title if tag and tag.title else default_title(index),
        "artist": (tag.artist if tag and tag.artist else None)
        or plan.metadata.artist
        or plan.metadata.album_artist
        or "",
        "album_artist": plan.metadata.album_artist or "",
        "album": plan.metadata.album or "",
        "year": plan.metadata.year or "",
        "position": (tag.position if tag and tag.position else "") or "",
        "catalog_number": plan.metadata.catalog_number or "",
    }
    template = plan.export.track_filename_template
    try:
        rendered = template.format(**fields)
    except KeyError as exc:
        raise MetadataError(
            f"filename template {template!r} uses unknown field {exc.args[0]!r}; "
            f"available: {', '.join(sorted(fields))}"
        ) from exc
    except (ValueError, IndexError) as exc:
        raise MetadataError(f"filename template {template!r} is malformed: {exc}") from exc
    return sanitize_component(rendered)


def track_filename(plan: ProcessingPlan, index: int) -> str:
    """Full filename including the container extension."""
    return f"{render_track_filename(plan, index)}.{plan.export.format}"

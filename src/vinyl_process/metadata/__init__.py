"""Metadata layer: naming and tag writing, independent from DSP."""

from vinyl_process.metadata.naming import render_track_filename, sanitize_component, track_filename
from vinyl_process.metadata.tagger import SUPPORTED_SUFFIXES, apply_tags, resolve_tags

__all__ = [
    "SUPPORTED_SUFFIXES",
    "apply_tags",
    "render_track_filename",
    "resolve_tags",
    "sanitize_component",
    "track_filename",
]

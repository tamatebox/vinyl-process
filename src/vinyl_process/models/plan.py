"""``processing_plan.json`` contract: the complete record of every decision.

Authored by the planning skills in ``.claude/skills/plan-*``. The executor adds
nothing subjective: **if a value is a choice, it must appear here.**

Each section carries an optional :class:`StageDecision` so the plan records not
only *what* was chosen but *who* chose it and *why* — the audit trail that makes
a 20-year-old archive re-derivable.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from vinyl_process.models.common import (
    Confidence,
    ContractModel,
    DocumentRef,
    SourceInfo,
    VersionedDocument,
)

NormalizeMode = Literal["album_peak", "album_rms", "album_gated_rms", "track_peak", "none"]
ExportFormat = Literal["flac", "wav", "aiff"]
DitherType = Literal["none", "tpdf"]


# --------------------------------------------------------------------------- #
# section bases
# --------------------------------------------------------------------------- #
class StageDecision(ContractModel):
    """Why this section looks the way it does."""

    skill: str | None = None
    rationale: str = ""
    confidence: Confidence | None = None
    inputs: list[str] = Field(default_factory=list)
    """Evidence consulted, e.g. ``["analysis.json#boundaries", "discogs:1873013"]``."""


class PlanSection(ContractModel):
    decision: StageDecision | None = None


class ToggleableSection(PlanSection):
    enabled: bool = True


class EngineSection(ToggleableSection):
    engine: str = "native"
    """Name resolved through the DSP registry (``vinyl-process engines``)."""


# --------------------------------------------------------------------------- #
# split
# --------------------------------------------------------------------------- #
class TrackBoundary(ContractModel):
    """A cut, in integer source samples. Titles live in the metadata section —
    the plan must not carry the same string twice.

    ``index`` is the track's position on the *album*, not within this plan: side B
    of a two-sided record continues where side A stopped, so both sides can be
    exported into one directory with correct numbering.
    """

    index: int = Field(ge=1)
    start_sample: int = Field(ge=0)
    end_sample: int = Field(gt=0)
    fade_in_ms: float = Field(default=0.0, ge=0.0)
    fade_out_ms: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def _check_range(self) -> TrackBoundary:
        if self.end_sample <= self.start_sample:
            raise ValueError(f"track {self.index}: end_sample must exceed start_sample")
        return self


class SplitPlan(EngineSection):
    tracks: list[TrackBoundary] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_tracks(self) -> SplitPlan:
        if not self.enabled:
            return self
        if not self.tracks:
            raise ValueError("split.enabled requires at least one track")
        indices = [t.index for t in self.tracks]
        first = indices[0]
        if indices != list(range(first, first + len(indices))):
            raise ValueError(f"track indices must be contiguous and ascending, got {indices}")
        for prev, cur in zip(self.tracks, self.tracks[1:], strict=False):
            if cur.start_sample < prev.end_sample:
                raise ValueError(f"tracks {prev.index} and {cur.index} overlap")
        return self


# --------------------------------------------------------------------------- #
# declick
# --------------------------------------------------------------------------- #
class DeclickPlan(EngineSection):
    algorithm: str = "block_ratio"
    """Engine-defined algorithm id; validated by the engine, not the schema."""

    threshold: float | None = Field(default=None, gt=0)
    """Engine-defined scale, and deliberately without a default.

    For ``block_ratio`` it is a ratio of energies read off
    ``clicks.threshold_sweep`` for *this* pressing: two sides of one album wanted
    different rungs, and a collection spans near-mint to heavily worn. A default
    here would be a decision taken on behalf of every record, which is the one
    thing this layer must not do. The engine refuses to run without it."""
    max_click_width_ms: float = Field(default=2.0, gt=0)
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    preset: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# normalize
# --------------------------------------------------------------------------- #
class NormalizePlan(EngineSection):
    mode: NormalizeMode = "album_peak"
    """``album_peak`` targets the sample peak, ``album_gated_rms`` the level of
    the programme with silence gated out, ``album_rms`` the ungated average of
    everything. ``track_peak`` exists but is discouraged because it destroys the
    relative dynamics between tracks of one side."""

    target_db: float = Field(default=-1.0, le=0.0)
    peak_ceiling_db: float | None = Field(default=None, le=0.0)
    """True-peak ceiling in dBTP. The executor caps the gain so the 4x-oversampled
    peak lands no higher — the guard an RMS target needs, since hitting a level
    reference says nothing about where the peaks end up. ``None`` leaves the gain
    uncapped; the executor still measures the true peak it produced and warns if
    the export had to clip."""


# --------------------------------------------------------------------------- #
# metadata
# --------------------------------------------------------------------------- #
class TrackTag(ContractModel):
    index: int = Field(ge=1)
    title: str
    artist: str | None = None
    position: str | None = None
    """Vinyl position as printed on the label, e.g. ``"A1"``."""


class MetadataPlan(ToggleableSection):
    total_tracks: int | None = Field(default=None, ge=1)
    """Tracks on the whole album, when this plan covers only one side. ``None``
    means "as many as this plan produces"."""

    album: str | None = None
    album_artist: str | None = None
    artist: str | None = None
    year: int | None = None
    genre: str | None = None
    styles: list[str] = Field(default_factory=list)
    label: str | None = None
    catalog_number: str | None = None
    discogs_release_id: str | None = None
    musicbrainz_release_id: str | None = None
    artwork_path: str | None = None
    tracks: list[TrackTag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_indices(self) -> MetadataPlan:
        indices = [t.index for t in self.tracks]
        if len(set(indices)) != len(indices):
            raise ValueError("metadata.tracks contains duplicate indices")
        return self

    def title_for(self, index: int) -> str | None:
        return next((t.title for t in self.tracks if t.index == index), None)

    def track_for(self, index: int) -> TrackTag | None:
        return next((t for t in self.tracks if t.index == index), None)


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #
class ExportPlan(PlanSection):
    format: ExportFormat = "flac"
    bit_depth: Literal[16, 24] = 24
    sample_rate: int | None = None
    """``None`` keeps the source rate — the archival default."""

    dither: DitherType = "none"
    dither_seed: int = 0
    """TPDF dither is generated from this seed, so dithered output stays
    bit-reproducible. Change the seed only to deliberately re-roll the noise."""

    track_filename_template: str = "{index:02d} - {title}"
    write_tags: bool = True


# --------------------------------------------------------------------------- #
# document
# --------------------------------------------------------------------------- #
class ProcessingPlan(VersionedDocument):
    document_type: Literal["processing_plan"] = "processing_plan"
    created_by: str | None = None
    """The skill or agent that authored this plan."""

    source: SourceInfo
    analysis: DocumentRef | None = None
    """The analysis this plan was derived from, pinned by digest."""

    split: SplitPlan
    declick: DeclickPlan
    normalize: NormalizePlan
    metadata: MetadataPlan
    export: ExportPlan
    notes: str = ""

    def track_indices(self) -> list[int]:
        if not self.split.enabled:
            return [1]
        return [t.index for t in self.split.tracks]

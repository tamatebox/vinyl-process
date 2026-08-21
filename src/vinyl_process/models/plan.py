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

NormalizeMode = Literal[
    "album_peak", "album_rms", "album_gated_rms", "album_lufs", "track_peak", "none"
]
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
# prefilter
# --------------------------------------------------------------------------- #
class PrefilterPlan(EngineSection):
    """DC blocking and the subsonic high-pass, applied to the whole side before
    the cuts.

    Two one-line filters share a section because they answer the same question —
    how much of what the transfer captured below the music should reach the
    listening copy — and neither justifies a stage of its own. Both are genuine
    preservation-versus-listening choices rather than constants, which is why they
    are here and not compiled in.

    Disabled by default, and the whole section is optional: a plan written before
    3.3 validates without it and executes to the same bytes.
    """

    enabled: bool = False
    """``False``, unlike every other stage. Removing anything from a transfer is
    a decision someone has to take, and the archival answer is often "nothing"."""

    dc_block: bool = False
    """Subtract each channel's mean. Exact, cheap, and unlike a filter it has no
    transition band — ``recording_info.dc_offset`` is what it removes."""

    highpass_hz: float | None = Field(default=None, gt=0.0)
    """Subsonic cutoff in Hz. ``None`` leaves the low end untouched.

    Practice is 20-30 Hz (Audacity's LP workflow, step 8); ``plan-prefilter``
    owns the choice and cites it. Nothing here defaults it, because a cutoff is a
    choice about the record in the room."""

    highpass_rolloff_db_per_octave: Literal[6, 12, 18, 24, 30, 36] = 24
    """Stated in the unit the practice is stated in. The engine converts it to a
    Butterworth order (``order = rolloff / 6``), which is deterministic and
    documented, so no decision leaks into Python."""


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
# decrackle
# --------------------------------------------------------------------------- #
class DecracklePlan(EngineSection):
    """Crackle is not clicks, and this is not ``declick`` with a lower threshold.

    Crackle is a bed of one-to-three sample events, repeated densely enough to be
    heard as a continuous texture rather than as countable ticks. Each is a weak
    outlier and there are thousands of them, so a collective threshold low enough
    to catch them interpolates the music long before it clears the bed. The tool
    for it examines every sample individually — which is why this is a separate
    stage with its own algorithm, and why lowering ``declick.threshold`` is the
    wrong lever.

    Runs on the whole side in the pre-split phase, after ``declick``: discrete
    defects before continuous ones. Optional and disabled by default.
    """

    enabled: bool = False

    algorithm: str = "curvature_ratio"
    """Engine-defined id, naming the *detector* — the half with evidence behind
    it, the same convention ``declick`` follows."""

    threshold: float | None = Field(default=None, gt=0)
    """``|curvature|`` against the mean ``|curvature|`` of its own neighbourhood,
    so **smaller is more aggressive** and there is deliberately no default.

    It is not ClickRepair's DeCrackle sensitivity: that scale runs the other way
    and is "an arbitrary percentage". Only that tool's *repair-rate band*
    transfers, and holding a setting against it is what ``plan-decrackle`` does."""

    max_event_width_samples: int = Field(default=3, ge=1, le=16)
    """Wider runs are dropped rather than repaired: at that width the event is a
    click and ``declick`` owns it. 1-3 samples is what crackle is."""

    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    params: dict[str, Any] = Field(default_factory=dict)
    """Engine extras: ``context_ms`` (5.0), ``interpolator``
    (``linear`` | ``hermite``)."""


# --------------------------------------------------------------------------- #
# mono merge
# --------------------------------------------------------------------------- #
class MonoMergePlan(EngineSection):
    """Fold a stereo capture of a **mono** record onto one signal.

    A mono groove is cut laterally, so both walls carry the same signal and the
    two channels are two observations of it. Damage is not shared to the same
    degree — one wall is often less damaged than the other — so this is a real
    redundancy the rest of the pipeline does not exploit.

    Last in the pre-split phase, after ``declick`` and ``decrackle``, because the
    reference is explicit that the walls are repaired independently first and
    merged afterwards. Optional and disabled by default: on a stereo record this
    stage destroys the image, so it is never something to leave on by habit.
    """

    enabled: bool = False

    strategy: Literal["level_matched", "left", "right"] = "level_matched"
    """``level_matched`` tracks the two walls' levels and merges them, which is the
    documented default. ``left`` and ``right`` take one wall and write it to both
    channels — the reference's own first option, for a record where one wall is
    plainly the better one and merging would only average the good with the bad.
    Which wall that is, is a listening decision, so it belongs here."""

    level_window_seconds: float = Field(default=1.0, gt=0.0)
    """The moving average the level match is computed over. Must be **long**: it is
    the only thing keeping the tracker from following a scratch rather than the
    recording, and it is what holds its own artefacts below audibility. See
    ``plan-mono-merge`` for what is cited and what is not."""


# --------------------------------------------------------------------------- #
# normalize
# --------------------------------------------------------------------------- #
class NormalizePlan(EngineSection):
    mode: NormalizeMode = "album_peak"
    """``album_peak`` targets the sample peak, ``album_gated_rms`` the level of
    the programme with silence gated out, ``album_rms`` the ungated average of
    everything, ``album_lufs`` the **loudness** of the programme — BS.1770's
    K-weighting and channel weighting on top of the same gates, so its target is
    in LUFS and not in dBFS. ``track_peak`` exists but is discouraged because it
    destroys the relative dynamics between tracks of one side."""

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

    disc_number: int | None = Field(default=None, ge=1)
    """Which disc of the set, when there is more than one. The two sides of one
    record are the same disc — the side is already in ``tracks[].position`` — so
    on a double album A/B are disc 1 and C/D are disc 2."""

    total_discs: int | None = Field(default=None, ge=1)

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

    comment: str | None = None
    """Free text for the COMMENT tag, composed by plan-metadata and written as
    given. It is where the provenance of the transfer goes — which pressing, and
    the chain it was played and digitised through, from the ``[rip]`` section of
    the configuration. Composed there and not here because what belongs in it is
    a choice, and choices live in the plan."""

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

    prefilter: PrefilterPlan = Field(default_factory=PrefilterPlan)
    """Optional, and disabled by default, so a pre-3.3 plan validates unchanged.
    The other five sections are required — see
    ``docs/adr/0012-the-executor-has-a-pre-split-phase.md`` for why the newer
    stages deviate from that convention rather than joining it."""

    split: SplitPlan
    declick: DeclickPlan
    decrackle: DecracklePlan = Field(default_factory=DecracklePlan)
    """Optional and disabled by default, like every stage added after 3.2."""

    mono_merge: MonoMergePlan = Field(default_factory=MonoMergePlan)
    """Optional and disabled by default. Last of the pre-split stages."""

    normalize: NormalizePlan
    metadata: MetadataPlan
    export: ExportPlan
    notes: str = ""

    def track_indices(self) -> list[int]:
        if not self.split.enabled:
            return [1]
        return [t.index for t in self.split.tracks]

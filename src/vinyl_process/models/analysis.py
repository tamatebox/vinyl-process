"""``analysis.json`` contract: pure measurements, no decisions.

One section per registered analyzer; the section key equals the analyzer name
(enforced by ``tests/contracts/test_analyzer_sections.py``). Every section is
optional so that ``analyze --analyzers rms_profile,clicks`` produces a valid,
partial document — consumers must handle absent sections.

The document contains no timestamps by default, so analysing the same file
twice yields byte-identical JSON.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import Field

from vinyl_process.models.common import (
    Confidence,
    ContractModel,
    Section,
    SourceInfo,
    VersionedDocument,
)

BoundaryMethod = Literal["silence", "rms_valley", "spectral_change"]
"""Detection method that produced a boundary candidate. Additive: new detectors
add a value (minor version bump)."""

AnalyzerStatus = Literal["ok", "failed", "skipped"]


# --------------------------------------------------------------------------- #
# leaf value objects
# --------------------------------------------------------------------------- #
class SilenceRegion(ContractModel):
    """A contiguous quiet stretch. Sample positions are inclusive-exclusive."""

    start_sample: int = Field(ge=0)
    end_sample: int = Field(ge=0)
    mean_rms_db: float
    duration_seconds: float = Field(ge=0)
    confidence: Confidence


class BoundaryCandidate(ContractModel):
    """One *candidate* cut point. Choosing among candidates is the Split
    skill's job — the analyzer never ranks them into a final track list."""

    sample: int = Field(ge=0)
    method: BoundaryMethod
    confidence: Confidence


class Histogram(ContractModel):
    """``len(bin_edges) == len(counts) + 1``, as produced by ``np.histogram``."""

    unit: str
    bin_edges: list[float]
    counts: list[int]


class BandEnergy(ContractModel):
    low_hz: float = Field(ge=0)
    high_hz: float = Field(gt=0)
    energy_db: float


class Percentiles(ContractModel):
    p05_db: float
    p50_db: float
    p95_db: float


class AnalyzerRun(ContractModel):
    """Record of one analyzer's execution, for debugging a partial document."""

    name: str
    version: str
    status: AnalyzerStatus
    message: str | None = None
    duration_ms: float | None = None  # only with --timings; breaks byte equality


# --------------------------------------------------------------------------- #
# sections (one per analyzer)
# --------------------------------------------------------------------------- #
class RecordingInfoSection(Section):
    """Electrical and format characteristics of the capture itself."""

    subtype: str
    bit_depth: int | None = None
    dc_offset: list[float]
    channel_peak_db: list[float]
    channel_rms_db: list[float]
    channel_balance_db: float | None = None
    channel_correlation: float | None = None


class RmsProfileSection(Section):
    """Windowed loudness envelope; the basis for silence and valley detection."""

    window_seconds: float = Field(gt=0)
    hop_seconds: float = Field(gt=0)
    values_db: list[float]


class SurfaceNoiseSection(Section):
    noise_floor_db: float
    stability_db: float = Field(ge=0)


class SilenceSection(Section):
    threshold_db: float
    regions: list[SilenceRegion]


class BoundariesSection(Section):
    """Candidates plus the playable region.

    ``lead_out_start_sample`` is where the trailing silence begins — for a
    full-side recording this is the run-out groove.
    """

    candidates: list[BoundaryCandidate]
    lead_in_end_sample: int | None = None
    lead_out_start_sample: int | None = None


class ClicksSection(Section):
    count: int = Field(ge=0)
    rate_per_minute: float = Field(ge=0)
    amplitude_histogram: Histogram
    width_histogram: Histogram
    density_per_minute: list[float]
    positions_sample: list[int]
    positions_truncated: bool = False


class PeaksSection(Section):
    peak_db: float
    peak_sample: int = Field(ge=0)
    rms_db: float
    crest_factor_db: float


class DynamicRangeSection(Section):
    dr_estimate_db: float
    loud_rms_db: float
    percentiles: Percentiles


class ClippingSection(Section):
    clipped_sample_count: int = Field(ge=0)
    clipped_region_count: int = Field(ge=0)
    longest_run_samples: int = Field(ge=0)
    ratio: float = Field(ge=0.0, le=1.0)


class SpectralSection(Section):
    centroid_mean_hz: float
    centroid_std_hz: float
    rolloff_mean_hz: float
    rumble_db: float
    hiss_db: float
    bands: list[BandEnergy]


class TransientsSection(Section):
    """Transient density over time — how percussive the material is, which
    tells the Declick skill how much false-positive risk a threshold carries."""

    hop_seconds: float = Field(gt=0)
    density_per_second: list[float]
    mean_per_second: float = Field(ge=0)
    peak_per_second: float = Field(ge=0)


# --------------------------------------------------------------------------- #
# document
# --------------------------------------------------------------------------- #
class AnalysisDocument(VersionedDocument):
    document_type: Literal["analysis"] = "analysis"
    generated_by: str
    source: SourceInfo
    config_digest: str | None = None
    analyzers: list[AnalyzerRun] = Field(default_factory=list)

    recording_info: RecordingInfoSection | None = None
    rms_profile: RmsProfileSection | None = None
    surface_noise: SurfaceNoiseSection | None = None
    silence: SilenceSection | None = None
    boundaries: BoundariesSection | None = None
    clicks: ClicksSection | None = None
    peaks: PeaksSection | None = None
    dynamic_range: DynamicRangeSection | None = None
    clipping: ClippingSection | None = None
    spectral: SpectralSection | None = None
    transients: TransientsSection | None = None

    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def section_fields(cls) -> tuple[str, ...]:
        """Field names holding analyzer sections, i.e. ``X | None`` where ``X``
        derives from :class:`Section`. Analyzer names must match these."""
        names: list[str] = []
        for name, field in cls.model_fields.items():
            for arg in get_args(field.annotation):
                if isinstance(arg, type) and issubclass(arg, Section):
                    names.append(name)
                    break
        return tuple(names)

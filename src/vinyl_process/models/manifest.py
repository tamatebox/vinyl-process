"""``manifest.json`` contract: the provenance record written by the executor.

Two runs of the same plan against the same source must produce manifests with
identical ``run_key``, identical ``applied_gain_db`` and identical output
digests. Only ``started_at`` / ``completed_at`` / ``environment`` may differ,
and none of them can affect audio.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from vinyl_process.models.common import ContractModel, DocumentRef, SourceInfo, VersionedDocument

StageName = Literal[
    "prefilter",
    "declick",
    "decrackle",
    "split",
    "normalize",
    "resample",
    "export",
    "metadata",
]
"""In pipeline order. ``prefilter``, ``declick`` and ``decrackle`` run **before**
``split``: repair works on the whole side, the way restoration practice orders it
— discrete defects before continuous ones — and a noise profile taken from the
medium's own groove is still reachable at that point.
See ``docs/adr/0012-the-executor-has-a-pre-split-phase.md``."""
StageStatus = Literal["applied", "skipped"]


class StageRecord(ContractModel):
    """What actually happened in one stage, including the engine that did it."""

    stage: StageName
    status: StageStatus
    engine: str | None = None
    engine_version: str | None = None
    params_digest: str | None = None
    """Digest of the plan section, so a manifest pins the exact parameters even
    if the plan file is later edited."""

    detail: str = ""


class OutputFile(ContractModel):
    track_index: int = Field(ge=1)
    path: str
    sha256: str
    bytes: int = Field(ge=0)
    num_samples: int = Field(ge=0)
    sample_rate: int = Field(gt=0)
    duration_seconds: float = Field(ge=0)
    source_start_sample: int = Field(ge=0)
    source_end_sample: int = Field(ge=0)
    tagged: bool = False


class ExecutionManifest(VersionedDocument):
    document_type: Literal["manifest"] = "manifest"
    generated_by: str
    run_key: str
    """Digest over (source digest, plan digest): identical inputs -> identical key."""

    source: SourceInfo
    plan: DocumentRef
    stages: list[StageRecord] = Field(default_factory=list)
    applied_gain_db: float | None = None
    """The one album-wide gain, exactly as applied. ``None`` for ``track_peak``,
    which has no single value, and when the stage was skipped."""

    applied_track_gains_db: list[float] | None = None
    """One gain per output, in ``outputs`` order. Only ``track_peak`` fills this."""

    applied_true_peak_db: float | None = None
    """True peak of the audio as exported — after gain, after any resampling.
    Above 0 means the export clipped; the matching warning says which track."""

    outputs: list[OutputFile] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    started_at: str
    completed_at: str
    warnings: list[str] = Field(default_factory=list)

    def output_digests(self) -> dict[str, str]:
        """``{relative filename: sha256}`` — the comparison basis for ``verify``."""
        from pathlib import PurePath

        return {PurePath(o.path).name: o.sha256 for o in self.outputs}

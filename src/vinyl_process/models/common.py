"""Shared building blocks for every data-contract document.

This module is the bottom of the contract stack: it may import only
:mod:`vinyl_process.errors` (a leaf) and pydantic.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from vinyl_process.errors import ContractError

SCHEMA_VERSION = "3.6"
"""``MAJOR.MINOR``. Additive changes bump MINOR; breaking changes bump MAJOR.

3.0 because ``silence.regions[].music_start_sample`` is required: a 2.x
``analysis.json`` no longer validates, so consumers must refuse it rather than
read a document missing the field the Split skill now cuts from.

3.1 adds ``metadata.disc_number``, ``metadata.total_discs`` and
``metadata.comment``. All three are optional with ``None`` defaults, so a 3.0
plan still validates and still executes to the same bytes.

3.3 adds ``processing_plan.prefilter`` and the manifest's ``prefilter`` stage
name. The section is optional with a disabled default, so a 3.1 or 3.2 plan
validates unchanged and executes to the same bytes — which is why this is a
*minor* bump even though the executor gained a phase. Making the section required
would have forced a major, and a major makes every archived plan
non-re-executable; re-execution is the promise this project is built on, so it
wins. See ``docs/adr/0012-the-executor-has-a-pre-split-phase.md``.

3.4 adds ``processing_plan.decrackle``, on the same terms: optional, disabled by
default, so a 3.3 plan validates unchanged and executes to the same bytes.

3.5 adds ``analysis.peaks.lufs`` (optional, ``None`` on a recording shorter than
one gating block) and the ``album_lufs`` value of ``normalize.mode``. Both are
additive: an older plan names an older mode and produces the same gain, and an
older analysis simply omits the field.

3.6 adds ``processing_plan.mono_merge``: optional, disabled by default, so a 3.5
plan validates unchanged and executes to the same bytes."""

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
"""How much a measurement can be trusted. 0 = worthless, 1 = certain."""


class ContractModel(BaseModel):
    """Base for every contract model: unknown fields are validation errors.

    ``extra="forbid"`` is deliberate — a typo in a hand-authored plan must fail
    loudly instead of being silently ignored by the executor.
    """

    model_config = ConfigDict(extra="forbid")


class VersionedDocument(ContractModel):
    """A document that is written to disk and read by another layer."""

    schema_version: str = SCHEMA_VERSION

    def major_version(self) -> int:
        return int(self.schema_version.split(".")[0])


class SourceInfo(ContractModel):
    """Identity of the source recording a document refers to.

    ``sha256`` is the anchor of reproducibility: the executor refuses to run a
    plan against audio whose digest does not match.
    """

    path: str
    sha256: str
    sample_rate: int = Field(gt=0)
    channels: int = Field(gt=0)
    num_samples: int = Field(ge=0)
    duration_seconds: float = Field(ge=0)


class DocumentRef(ContractModel):
    """Reference from one document to another, pinned by digest."""

    path: str
    sha256: str


class SectionMeta(ContractModel):
    """Provenance of one analyzer section.

    Filled in by the analyzer runner, except ``confidence``, which the analyzer
    itself sets when it can quantify how much its own output can be trusted.
    """

    analyzer: str = ""
    version: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    confidence: Confidence | None = None


class Section(ContractModel):
    """Base for analyzer output sections: one section per registered analyzer."""

    meta: SectionMeta = Field(default_factory=SectionMeta)


def check_major_version(document: VersionedDocument) -> None:
    """Raise :class:`ContractError` if the document's major version is foreign."""
    expected = int(SCHEMA_VERSION.split(".")[0])
    if document.major_version() != expected:
        raise ContractError(
            f"unsupported schema major version {document.schema_version!r}; "
            f"this tool supports {SCHEMA_VERSION}"
        )

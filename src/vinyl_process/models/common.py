"""Shared building blocks for every data-contract document.

This module is the bottom of the contract stack: it may import only
:mod:`vinyl_process.errors` (a leaf) and pydantic.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from vinyl_process.errors import ContractError

SCHEMA_VERSION = "2.2"
"""``MAJOR.MINOR``. Additive changes bump MINOR; breaking changes bump MAJOR."""

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

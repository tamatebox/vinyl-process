"""Data contracts connecting the three layers.

These pydantic models are the single source of truth. The JSON Schemas under
``schemas/`` are generated from them by ``vinyl-process schemas`` and committed
so non-Python consumers (planning skills, other tools) have a formal contract.
"""

from vinyl_process.models.analysis import AnalysisDocument
from vinyl_process.models.common import (
    SCHEMA_VERSION,
    ContractModel,
    DocumentRef,
    Section,
    SectionMeta,
    SourceInfo,
    VersionedDocument,
    check_major_version,
)
from vinyl_process.models.manifest import ExecutionManifest, OutputFile, StageRecord
from vinyl_process.models.plan import ProcessingPlan, StageDecision

#: Every document that can be written to disk, keyed by its ``document_type``.
DOCUMENT_MODELS: dict[str, type[VersionedDocument]] = {
    "analysis": AnalysisDocument,
    "processing_plan": ProcessingPlan,
    "manifest": ExecutionManifest,
}

__all__ = [
    "DOCUMENT_MODELS",
    "SCHEMA_VERSION",
    "AnalysisDocument",
    "ContractModel",
    "DocumentRef",
    "ExecutionManifest",
    "OutputFile",
    "ProcessingPlan",
    "Section",
    "SectionMeta",
    "SourceInfo",
    "StageDecision",
    "StageRecord",
    "VersionedDocument",
    "check_major_version",
]

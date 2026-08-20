"""Exception hierarchy.

Every error raised on purpose by this package derives from
:class:`VinylProcessError` and carries an :attr:`exit_code` so the CLI can turn
it into a stable process exit status without ``isinstance`` ladders.
"""

from __future__ import annotations

__all__ = [
    "AnalysisError",
    "AudioIOError",
    "ConfigError",
    "ContractError",
    "DeterminismError",
    "EngineNotFoundError",
    "EngineUnavailableError",
    "ExecutionError",
    "MetadataError",
    "PlanValidationError",
    "UnsupportedOperationError",
    "VinylProcessError",
    "WorkspaceError",
]


class VinylProcessError(Exception):
    """Base class for all deliberate failures."""

    exit_code = 1


class ConfigError(VinylProcessError):
    """Configuration file or environment override is invalid."""

    exit_code = 78  # EX_CONFIG


class AudioIOError(VinylProcessError):
    """An audio file could not be read or written."""

    exit_code = 74  # EX_IOERR


class AnalysisError(VinylProcessError):
    """An analyzer could not produce a measurement."""

    exit_code = 65


class ContractError(VinylProcessError):
    """A JSON document does not satisfy its schema."""

    exit_code = 65  # EX_DATAERR


class PlanValidationError(ContractError):
    """A processing plan is structurally valid but not executable."""

    exit_code = 65


class EngineNotFoundError(VinylProcessError):
    """The plan names a DSP engine that is not registered."""

    exit_code = 69  # EX_UNAVAILABLE


class EngineUnavailableError(VinylProcessError):
    """The engine is registered but its external dependency is missing."""

    exit_code = 69


class UnsupportedOperationError(VinylProcessError):
    """The engine does not implement the requested operation."""

    exit_code = 69


class ExecutionError(VinylProcessError):
    """A stage failed while executing."""

    exit_code = 70  # EX_SOFTWARE


class DeterminismError(ExecutionError):
    """Re-execution produced different bytes than the recorded manifest."""

    exit_code = 70


class MetadataError(VinylProcessError):
    """Metadata could not be resolved or written."""

    exit_code = 65


class WorkspaceError(VinylProcessError):
    """A job workspace is missing or malformed."""

    exit_code = 66  # EX_NOINPUT

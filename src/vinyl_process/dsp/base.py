"""The DSP engine interface.

Engines transform audio exactly as the plan parameterises them. They never
choose parameters, never read ``analysis.json``, and never use randomness or the
wall clock: identical audio + identical parameters -> identical output.

An engine implements only the capabilities it has; the executor checks
capabilities before dispatching, so a partial engine is a first-class citizen
(``ffmpeg`` deliberately does not implement ``split``).

Converting a canonical plan parameter into an engine's own units (dB to a linear
factor, a click width to a filter window) is part of an engine's contract, not a
decision — it must be deterministic and documented in the engine's docstring.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from vinyl_process.audio import AudioBuffer
from vinyl_process.errors import EngineUnavailableError, UnsupportedOperationError
from vinyl_process.models.plan import (
    DeclickPlan,
    DecracklePlan,
    PrefilterPlan,
    TrackBoundary,
)

Capability = Literal["prefilter", "split", "declick", "decrackle", "gain"]
ALL_CAPABILITIES: frozenset[Capability] = frozenset(
    {"prefilter", "split", "declick", "decrackle", "gain"}
)


class DspEngine(ABC):
    """Base class for every DSP engine."""

    name: str

    @abstractmethod
    def capabilities(self) -> frozenset[Capability]:
        """Operations this engine implements."""

    @abstractmethod
    def version(self) -> str:
        """Implementation version, recorded in the manifest for drift detection."""

    def is_available(self) -> bool:
        """False when an external dependency (e.g. an ffmpeg binary) is missing."""
        return True

    def prefilter(self, audio: AudioBuffer, plan: PrefilterPlan) -> AudioBuffer:
        raise UnsupportedOperationError(f"engine {self.name!r} does not support prefilter")

    def split(self, audio: AudioBuffer, tracks: list[TrackBoundary]) -> list[AudioBuffer]:
        raise UnsupportedOperationError(f"engine {self.name!r} does not support split")

    def declick(self, audio: AudioBuffer, plan: DeclickPlan) -> AudioBuffer:
        raise UnsupportedOperationError(f"engine {self.name!r} does not support declick")

    def decrackle(self, audio: AudioBuffer, plan: DecracklePlan) -> AudioBuffer:
        raise UnsupportedOperationError(f"engine {self.name!r} does not support decrackle")

    def apply_gain(self, audio: AudioBuffer, gain_db: float) -> AudioBuffer:
        raise UnsupportedOperationError(f"engine {self.name!r} does not support gain")

    def require(self, capability: Capability) -> None:
        """Fail before touching audio if this engine cannot do the job."""
        if capability not in self.capabilities():
            raise UnsupportedOperationError(
                f"engine {self.name!r} does not support {capability}; "
                f"it supports: {', '.join(sorted(self.capabilities())) or 'nothing'}"
            )
        if not self.is_available():
            raise EngineUnavailableError(
                f"engine {self.name!r} is registered but not available on this system"
            )

    def describe(self) -> str:
        status = "available" if self.is_available() else "UNAVAILABLE"
        caps = ", ".join(sorted(self.capabilities())) or "-"
        return f"{self.name} [{status}] {caps} ({self.version()})"

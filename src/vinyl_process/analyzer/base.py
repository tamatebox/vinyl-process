"""The analyzer plug-in interface.

An analyzer is a pure function ``AnalyzerContext -> Section``. It measures and
nothing else: it must not choose processing parameters, write files, or consult
anything outside its context. Adding a measurement is therefore one module plus
one section model — see ``docs/architecture.md``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from vinyl_process.audio import AudioBuffer, FormatInfo
from vinyl_process.errors import AnalysisError
from vinyl_process.models.common import Section, SourceInfo

__all__ = ["AnalyzerContext", "AnalyzerFn", "AnalyzerSpec"]

SectionT = TypeVar("SectionT", bound=Section)


@dataclass(frozen=True)
class AnalyzerContext:
    """Everything an analyzer is allowed to look at."""

    audio: AudioBuffer
    source: SourceInfo
    format: FormatInfo
    params: Mapping[str, Any]
    """Declared defaults merged with ``[analyzer.<name>]`` config overrides."""

    sections: Mapping[str, Section]
    """Sections already produced this run, keyed by analyzer name."""

    def number(self, key: str) -> float:
        try:
            return float(self.params[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise AnalysisError(f"parameter {key!r} must be a number: {exc}") from exc

    def integer(self, key: str) -> int:
        return int(self.number(key))

    def section(self, name: str) -> Section:
        """A dependency's section, or :class:`AnalysisError` if it is missing.

        Missing means the dependency failed or was excluded from the selection;
        the runner turns this into a ``skipped`` record rather than a crash.
        """
        try:
            return self.sections[name]
        except KeyError:
            raise AnalysisError(f"required section {name!r} is not available") from None

    def typed_section(self, name: str, kind: type[SectionT]) -> SectionT:
        """A dependency's section, checked against the model it must be."""
        section = self.section(name)
        if not isinstance(section, kind):
            raise AnalysisError(
                f"section {name!r} is a {type(section).__name__}, expected {kind.__name__}"
            )
        return section


AnalyzerFn = Callable[[AnalyzerContext], Section]


@dataclass(frozen=True)
class AnalyzerSpec:
    """Registration record for one analyzer."""

    name: str
    """Must equal the field name of its section in ``AnalysisDocument``."""

    version: str
    description: str
    requires: tuple[str, ...]
    defaults: Mapping[str, Any]
    fn: AnalyzerFn

    def merge_params(self, overrides: Mapping[str, Any]) -> dict[str, Any]:
        """Declared defaults overlaid with config overrides (unknown keys fail)."""
        unknown = set(overrides) - set(self.defaults)
        if unknown:
            raise AnalysisError(
                f"analyzer {self.name!r} has no parameter(s) {sorted(unknown)}; "
                f"known: {sorted(self.defaults)}"
            )
        return {**self.defaults, **overrides}

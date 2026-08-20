"""Runs the selected analyzers and assembles ``analysis.json``.

The runner is deliberately dumb: it resolves the dependency order, hands each
analyzer its parameters, stamps provenance onto the section it returns, and
records what happened. It contains no measurement logic and no decisions.

A failing analyzer degrades the document instead of aborting the run — a partial
``analysis.json`` with an explicit ``failed`` record is far more useful than no
document at all, and every consumer already has to handle absent sections.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path

from vinyl_process import __version__
from vinyl_process.analyzer.base import AnalyzerContext
from vinyl_process.analyzer.registry import resolve_order
from vinyl_process.audio import format_info, load_audio, source_info_for
from vinyl_process.config import Config, default_config
from vinyl_process.errors import AnalysisError
from vinyl_process.log import get_logger
from vinyl_process.models.analysis import (
    AnalysisDocument,
    AnalyzerRun,
    BoundariesSection,
    ClippingSection,
)
from vinyl_process.models.common import Section

logger = get_logger(__name__)


def run_analysis(
    path: str | Path,
    *,
    analyzers: Iterable[str] | None = None,
    config: Config | None = None,
    timings: bool = False,
) -> AnalysisDocument:
    """Measure ``path`` and return the analysis document.

    ``analyzers`` selects a subset by name (dependencies are pulled in
    automatically); ``None`` runs everything registered. ``timings`` records wall
    clock per analyzer, which is useful for profiling but breaks byte-for-byte
    reproducibility of the document, so it is off by default.
    """
    settings = config or default_config()
    source = source_info_for(path)
    audio = load_audio(path)
    fmt = format_info(path)

    known_fields = set(AnalysisDocument.section_fields())
    sections: dict[str, Section] = {}
    runs: list[AnalyzerRun] = []
    warnings: list[str] = []

    for spec in resolve_order(analyzers):
        if spec.name not in known_fields:
            raise AnalysisError(
                f"analyzer {spec.name!r} has no matching field in AnalysisDocument; "
                "every analyzer needs a section model"
            )

        missing = [name for name in spec.requires if name not in sections]
        if missing:
            message = f"missing dependencies: {', '.join(missing)}"
            runs.append(
                AnalyzerRun(name=spec.name, version=spec.version, status="skipped", message=message)
            )
            warnings.append(f"{spec.name}: skipped ({message})")
            continue

        try:
            params = spec.merge_params(settings.analyzer_params(spec.name))
            context = AnalyzerContext(
                audio=audio, source=source, format=fmt, params=params, sections=sections
            )
            started = time.perf_counter()
            section = spec.fn(context)
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
        except Exception as exc:  # one broken analyzer must not lose the rest
            logger.exception("analyzer %s failed", spec.name)
            runs.append(
                AnalyzerRun(name=spec.name, version=spec.version, status="failed", message=str(exc))
            )
            warnings.append(f"{spec.name}: failed ({exc})")
            continue

        sections[spec.name] = section.model_copy(
            update={
                "meta": section.meta.model_copy(
                    update={"analyzer": spec.name, "version": spec.version, "params": dict(params)}
                )
            }
        )
        runs.append(
            AnalyzerRun(
                name=spec.name,
                version=spec.version,
                status="ok",
                duration_ms=elapsed_ms if timings else None,
            )
        )
        logger.info("analyzer %s ok (%.1f ms)", spec.name, elapsed_ms)

    return AnalysisDocument(
        generated_by=f"vinyl-process {__version__}",
        source=source,
        config_digest=settings.digest(),
        analyzers=runs,
        warnings=warnings + _observations(sections),
        **sections,  # type: ignore[arg-type]
    )


def _observations(sections: dict[str, Section]) -> list[str]:
    """Factual notes about the measurements, never advice.

    Advice would be a decision, and decisions belong to the planning skills.
    """
    notes: list[str] = []
    clipping = sections.get("clipping")
    if isinstance(clipping, ClippingSection) and clipping.clipped_region_count > 0:
        notes.append(
            f"clipping: {clipping.clipped_region_count} region(s), "
            f"{clipping.clipped_sample_count} sample(s) at full scale"
        )
    boundaries = sections.get("boundaries")
    if isinstance(boundaries, BoundariesSection) and not boundaries.candidates:
        notes.append("no boundary candidates found")
    return notes

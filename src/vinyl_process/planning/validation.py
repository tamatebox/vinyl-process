"""Plan validation: is this plan *executable*, not is it *good*?

Pydantic already guarantees a plan is structurally valid. This module answers the
questions a schema cannot: does the named engine exist and can it do the job, do
the cuts fit inside the recording, do two tracks want the same filename, does the
digest still match the audio on disk.

It contains no decision logic: it never changes a plan, only reports on it.
Skills run it before handing a plan over (``vinyl-process lint``); the executor
runs the subset that needs no analysis document and refuses to execute on error.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from vinyl_process.audio import source_info_for
from vinyl_process.dsp.registry import get_engine
from vinyl_process.errors import PlanValidationError, VinylProcessError
from vinyl_process.hashing import digest_file
from vinyl_process.models.analysis import AnalysisDocument
from vinyl_process.models.common import check_major_version
from vinyl_process.models.plan import ProcessingPlan

Severity = Literal["error", "warning", "info"]

MIN_REASONABLE_TRACK_SECONDS = 5.0


@dataclass(frozen=True)
class Finding:
    severity: Severity
    code: str
    message: str
    location: str = ""

    def __str__(self) -> str:
        where = f" [{self.location}]" if self.location else ""
        return f"{self.severity}: {self.code}{where}: {self.message}"


def validate_plan(
    plan: ProcessingPlan,
    *,
    audio_path: str | Path | None = None,
    analysis: AnalysisDocument | None = None,
    analysis_digest: str | None = None,
    check_digest: bool = True,
) -> list[Finding]:
    """Collect everything questionable about ``plan``, worst first."""
    findings: list[Finding] = []
    findings += _check_version(plan)
    findings += _check_engines(plan)
    findings += _check_tracks(plan)
    findings += _check_naming(plan)
    findings += _check_export(plan)
    if audio_path is not None:
        findings += _check_source(plan, Path(audio_path), check_digest=check_digest)
    if analysis is not None:
        findings += _check_against_analysis(plan, analysis, analysis_digest)
    order: dict[Severity, int] = {"error": 0, "warning": 1, "info": 2}
    return sorted(findings, key=lambda finding: order[finding.severity])


def errors(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.severity == "error"]


def raise_for_errors(findings: list[Finding]) -> None:
    """Raise :class:`PlanValidationError` if anything is fatal."""
    fatal = errors(findings)
    if fatal:
        detail = "\n".join(f"  - {finding}" for finding in fatal)
        raise PlanValidationError(f"plan is not executable:\n{detail}")


# --------------------------------------------------------------------------- #
# individual checks
# --------------------------------------------------------------------------- #
def _check_version(plan: ProcessingPlan) -> list[Finding]:
    try:
        check_major_version(plan)
    except VinylProcessError as exc:
        return [Finding("error", "schema-version", str(exc), "schema_version")]
    return []


def _check_engines(plan: ProcessingPlan) -> list[Finding]:
    findings: list[Finding] = []
    stages = (
        ("split", plan.split.enabled, plan.split.engine, "split"),
        ("declick", plan.declick.enabled, plan.declick.engine, "declick"),
        (
            "normalize",
            plan.normalize.enabled and plan.normalize.mode != "none",
            plan.normalize.engine,
            "gain",
        ),
    )
    for section, enabled, engine_name, capability in stages:
        if not enabled:
            continue
        try:
            engine = get_engine(engine_name)
        except VinylProcessError as exc:
            findings.append(Finding("error", "unknown-engine", str(exc), f"{section}.engine"))
            continue
        if capability not in engine.capabilities():
            findings.append(
                Finding(
                    "error",
                    "engine-capability",
                    f"engine {engine_name!r} cannot perform {capability}",
                    f"{section}.engine",
                )
            )
        elif not engine.is_available():
            findings.append(
                Finding(
                    "error",
                    "engine-unavailable",
                    f"engine {engine_name!r} is not available on this system",
                    f"{section}.engine",
                )
            )
    return findings


def _check_tracks(plan: ProcessingPlan) -> list[Finding]:
    if not plan.split.enabled:
        if len(plan.metadata.tracks) > 1:
            return [
                Finding(
                    "warning",
                    "unsplit-multitrack",
                    f"split is disabled but metadata lists {len(plan.metadata.tracks)} tracks; "
                    "only track 1's tags will be applied",
                    "split.enabled",
                )
            ]
        return []

    findings: list[Finding] = []
    sample_rate = plan.source.sample_rate
    for track in plan.split.tracks:
        duration = (track.end_sample - track.start_sample) / sample_rate
        if duration < MIN_REASONABLE_TRACK_SECONDS:
            findings.append(
                Finding(
                    "warning",
                    "short-track",
                    f"track {track.index} is {duration:.2f}s long",
                    f"split.tracks[{track.index}]",
                )
            )
        if plan.source.num_samples and track.end_sample > plan.source.num_samples:
            findings.append(
                Finding(
                    "error",
                    "track-past-end",
                    f"track {track.index} ends at sample {track.end_sample}, past the "
                    f"recording's {plan.source.num_samples} samples",
                    f"split.tracks[{track.index}]",
                )
            )
        fade = (track.fade_in_ms + track.fade_out_ms) / 1000.0
        if fade > duration:
            findings.append(
                Finding(
                    "error",
                    "fade-longer-than-track",
                    f"track {track.index}: fades total {fade:.3f}s but the track is "
                    f"{duration:.3f}s",
                    f"split.tracks[{track.index}]",
                )
            )
        if plan.metadata.enabled and plan.metadata.title_for(track.index) is None:
            findings.append(
                Finding(
                    "warning",
                    "missing-title",
                    f"no metadata title for track {track.index}; the filename will fall back "
                    "to a generic name",
                    f"metadata.tracks[{track.index}]",
                )
            )
    extra = {tag.index for tag in plan.metadata.tracks} - set(plan.track_indices())
    if extra:
        findings.append(
            Finding(
                "warning",
                "orphan-metadata",
                f"metadata describes track(s) {sorted(extra)} that the split does not produce",
                "metadata.tracks",
            )
        )
    return findings


def _check_naming(plan: ProcessingPlan) -> list[Finding]:
    """Render every filename now, so a template typo fails before any DSP runs."""
    from vinyl_process.metadata.naming import render_track_filename

    findings: list[Finding] = []
    seen: dict[str, int] = {}
    for index in plan.track_indices():
        try:
            name = render_track_filename(plan, index)
        except VinylProcessError as exc:
            findings.append(
                Finding("error", "filename-template", str(exc), "export.track_filename_template")
            )
            break
        if name in seen:
            findings.append(
                Finding(
                    "error",
                    "filename-collision",
                    f"tracks {seen[name]} and {index} both render to {name!r}",
                    "export.track_filename_template",
                )
            )
        seen[name] = index
    return findings


def _check_export(plan: ProcessingPlan) -> list[Finding]:
    findings: list[Finding] = []
    if plan.export.dither != "none" and plan.export.bit_depth >= 24:
        findings.append(
            Finding(
                "info",
                "pointless-dither",
                "dither at 24 bit is below the noise floor of any pressing; it only costs "
                "entropy in the archive",
                "export.dither",
            )
        )
    if plan.export.sample_rate is not None and plan.export.sample_rate != plan.source.sample_rate:
        findings.append(
            Finding(
                "info",
                "resampling",
                f"export resamples {plan.source.sample_rate} Hz -> {plan.export.sample_rate} Hz",
                "export.sample_rate",
            )
        )
    if plan.export.write_tags and plan.metadata.enabled and not plan.metadata.album:
        findings.append(
            Finding("warning", "no-album-title", "metadata has no album title", "metadata.album")
        )
    return findings


def _check_source(plan: ProcessingPlan, audio_path: Path, *, check_digest: bool) -> list[Finding]:
    if not audio_path.is_file():
        return [Finding("error", "missing-audio", f"audio file not found: {audio_path}", "source")]

    findings: list[Finding] = []
    if check_digest:
        actual = digest_file(audio_path)
        if actual != plan.source.sha256:
            findings.append(
                Finding(
                    "error",
                    "source-mismatch",
                    f"{audio_path} has sha256 {actual[:12]}… but the plan records "
                    f"{plan.source.sha256[:12]}…",
                    "source.sha256",
                )
            )

    # Length is checked even when the digest is not: with --no-verify-source the
    # digest cannot catch a truncated file, and the cuts would run off the end.
    actual_frames = source_info_for(audio_path).num_samples
    if actual_frames != plan.source.num_samples:
        findings.append(
            Finding(
                "error",
                "source-length-mismatch",
                f"{audio_path} holds {actual_frames} samples but the plan was built for "
                f"{plan.source.num_samples}",
                "source.num_samples",
            )
        )
    return findings


def _check_against_analysis(
    plan: ProcessingPlan, analysis: AnalysisDocument, analysis_digest: str | None = None
) -> list[Finding]:
    findings: list[Finding] = []
    if (
        analysis_digest is not None
        and plan.analysis is not None
        and plan.analysis.sha256 != analysis_digest
    ):
        findings.append(
            Finding(
                "warning",
                "analysis-digest-drift",
                "the analysis document has changed since the plan was written "
                f"({plan.analysis.sha256[:12]}… -> {analysis_digest[:12]}…)",
                "analysis.sha256",
            )
        )
    if analysis.source.sha256 != plan.source.sha256:
        findings.append(
            Finding(
                "error",
                "analysis-mismatch",
                "the analysis document describes a different recording than the plan",
                "analysis",
            )
        )
        return findings
    if (
        analysis.clipping is not None
        and analysis.clipping.clipped_region_count > 0
        and plan.normalize.enabled
        and plan.normalize.mode != "none"
    ):
        findings.append(
            Finding(
                "warning",
                "normalize-clipped-source",
                f"the source has {analysis.clipping.clipped_region_count} clipped region(s); "
                "normalizing amplifies the damage instead of repairing it",
                "normalize",
            )
        )
    if plan.split.enabled and analysis.boundaries is not None:
        lead_out = analysis.boundaries.lead_out_start_sample
        last = plan.split.tracks[-1].end_sample
        if lead_out is not None and last > lead_out + plan.source.sample_rate:
            findings.append(
                Finding(
                    "info",
                    "track-into-runout",
                    f"the last track ends {(last - lead_out) / plan.source.sample_rate:.1f}s "
                    "into the trailing silence / run-out",
                    "split.tracks",
                )
            )
    return findings

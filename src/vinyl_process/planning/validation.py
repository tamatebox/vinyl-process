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

MIN_HEADROOM_DB = 0.5

THIN_TRUE_PEAK_DB = -0.7
"""A lossy transcode wants 1 dB of true-peak headroom; below 0.3 dB of shortfall
nobody would act on the difference, so that is where the finding starts."""


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
    findings += _check_cuts(plan)
    findings += _check_naming(plan)
    findings += _check_normalize(plan)
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


def _check_cuts(plan: ProcessingPlan) -> list[Finding]:
    """How the cuts meet the audio: gapless requires the opposite of the default.

    A side meant to play continuously is expressed by contiguous boundaries
    (``end_sample == next start_sample``) so the tracks concatenate back into the
    original samples. A fade at such a boundary silently defeats that: every
    transition gets a dip, and the reassembled side is no longer the recording.

    The reverse case — a cut into recorded material with no fade — is a click,
    because a vinyl cut lands in surface noise rather than digital silence.
    """
    if not plan.split.enabled or len(plan.split.tracks) < 1:
        return []

    findings: list[Finding] = []
    for previous, current in zip(plan.split.tracks, plan.split.tracks[1:], strict=False):
        if current.start_sample != previous.end_sample:
            continue
        if previous.fade_out_ms > 0 or current.fade_in_ms > 0:
            findings.append(
                Finding(
                    "error",
                    "gapless-fade",
                    f"tracks {previous.index} and {current.index} are contiguous, which means "
                    "gapless playback, but a fade is applied at the join: the tracks would no "
                    "longer concatenate back into the recording",
                    f"split.tracks[{current.index}]",
                )
            )

    hard_cuts = sum(
        (track.fade_in_ms == 0 and track.start_sample > 0)
        + (track.fade_out_ms == 0 and track.end_sample < plan.source.num_samples)
        for track in plan.split.tracks
    )
    contiguous = sum(
        current.start_sample == previous.end_sample
        for previous, current in zip(plan.split.tracks, plan.split.tracks[1:], strict=False)
    )
    if hard_cuts and contiguous < len(plan.split.tracks) - 1:
        findings.append(
            Finding(
                "warning",
                "hard-cut",
                f"{hard_cuts} track edge(s) cut into the recording with no fade; a vinyl cut "
                "lands in surface noise, not silence, so the step is audible as a click",
                "split.tracks",
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


def _check_normalize(plan: ProcessingPlan) -> list[Finding]:
    """What can be said about the level decision from the plan alone.

    The executor runs this too, so an unguarded RMS target reaches the run's own
    warnings even when nobody linted the plan first.
    """
    normalize = plan.normalize
    if not normalize.enabled or normalize.mode == "none":
        return []

    findings: list[Finding] = []
    if normalize.mode in ("album_rms", "album_gated_rms") and normalize.peak_ceiling_db is None:
        findings.append(
            Finding(
                "warning",
                "rms-without-peak-ceiling",
                f"{normalize.mode} hits a level target and says nothing about where the peaks "
                "land; without normalize.peak_ceiling_db the export can clip",
                "normalize.peak_ceiling_db",
            )
        )
    if normalize.mode == "album_rms":
        findings.append(
            Finding(
                "info",
                "ungated-rms",
                "album_rms averages the inter-track gaps and the lead-in in with the music, so "
                "a side with long gaps measures quiet and normalizes loud; album_gated_rms "
                "measures the programme only",
                "normalize.mode",
            )
        )
    # The ceiling is what the peaks actually end up against: an explicit
    # peak_ceiling_db when there is one, otherwise the target the peak modes aim
    # the sample peak at. An RMS target is not a ceiling, so it says nothing here.
    if normalize.peak_ceiling_db is not None:
        effective, where = normalize.peak_ceiling_db, "normalize.peak_ceiling_db"
    elif normalize.mode in ("album_peak", "track_peak"):
        effective, where = normalize.target_db, "normalize.target_db"
    else:
        return findings
    if effective > -MIN_HEADROOM_DB:
        findings.append(
            Finding(
                "warning",
                "no-headroom",
                f"a ceiling of {effective:+.2f} dB leaves nothing for inter-sample peaks; "
                "-1.0 dB is the standard ceiling and is what a later lossy transcode needs",
                where,
            )
        )
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
    findings += _check_normalize_against_analysis(plan, analysis)
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


def _predicted_gain_db(plan: ProcessingPlan, analysis: AnalysisDocument) -> float | None:
    """What the executor's gain will roughly come to, from the analysis.

    Roughly, because the analyzer measured the whole recording while the executor
    measures the tracks after the split and after declicking: the lead-in's
    stylus drop and the run-out are in the first figure and not the second. Peak
    modes therefore tend to under-predict the gain and RMS modes to over-predict
    it. Good enough to spot a plan that will clip, not good enough to put in a
    plan's rationale.
    """
    peaks = analysis.peaks
    if peaks is None or not plan.normalize.enabled:
        return None
    mode = plan.normalize.mode
    if mode in ("album_peak", "track_peak"):
        reference: float = peaks.peak_db
    elif mode == "album_gated_rms":
        reference = peaks.gated_rms_db if peaks.gated_rms_db is not None else peaks.rms_db
    elif mode == "album_rms":
        reference = peaks.rms_db
    else:
        return None
    return plan.normalize.target_db - reference


def _check_normalize_against_analysis(
    plan: ProcessingPlan, analysis: AnalysisDocument
) -> list[Finding]:
    findings: list[Finding] = []
    gain = _predicted_gain_db(plan, analysis)
    if gain is None:
        return findings

    if analysis.clipping is not None and analysis.clipping.clipped_region_count > 0 and gain > 0:
        findings.append(
            Finding(
                "warning",
                "normalize-clipped-source",
                f"the source has {analysis.clipping.clipped_region_count} clipped region(s) and "
                f"this plan turns the level up by about {gain:+.1f} dB; normalizing amplifies the "
                "damage instead of repairing it",
                "normalize",
            )
        )

    peaks = analysis.peaks
    if peaks is None or peaks.true_peak_db is None or plan.normalize.peak_ceiling_db is not None:
        # With a ceiling set the executor caps the gain itself, so there is
        # nothing here for a warning to add.
        return findings
    predicted = peaks.true_peak_db + gain
    if predicted > 0.0:
        findings.append(
            Finding(
                "warning",
                "true-peak-over-full-scale",
                f"the true peak lands near {predicted:+.1f} dBTP, so the export clips; set "
                "normalize.peak_ceiling_db or lower normalize.target_db",
                "normalize.target_db",
            )
        )
    elif predicted > THIN_TRUE_PEAK_DB:
        findings.append(
            Finding(
                "info",
                "thin-true-peak-headroom",
                f"the true peak lands near {predicted:+.1f} dBTP — under the 1 dB a lossy "
                "transcode of this album would want, though the FLAC itself is fine",
                "normalize.target_db",
            )
        )
    return findings

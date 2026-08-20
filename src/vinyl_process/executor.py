"""Plan executor: runs a ``ProcessingPlan`` end to end, deterministically.

``split -> declick -> normalize -> resample -> export -> tag -> manifest``.

Every subjective value comes from the plan. This module performs only the
arithmetic the plan implies, and it deliberately never reads ``analysis.json``:
if the executor needed the measurements to decide something, that something would
be a decision, and decisions belong to the planning skills.

The manifest it writes is the receipt: source and plan digests, the engine and
version that ran each stage, a digest of each stage's parameters, and the digest
of every file produced.
"""

from __future__ import annotations

import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from vinyl_process import __version__
from vinyl_process.audio import AudioBuffer, load_audio, save_audio, source_info_for
from vinyl_process.dsp.base import Capability, DspEngine
from vinyl_process.dsp.registry import get_engine
from vinyl_process.errors import ExecutionError
from vinyl_process.hashing import digest_file, digest_json
from vinyl_process.log import get_logger
from vinyl_process.metadata import apply_tags, track_filename
from vinyl_process.metadata.tagger import SUPPORTED_SUFFIXES
from vinyl_process.models.common import ContractModel, DocumentRef
from vinyl_process.models.manifest import (
    ExecutionManifest,
    OutputFile,
    StageName,
    StageRecord,
    StageStatus,
)
from vinyl_process.models.plan import ProcessingPlan, TrackBoundary
from vinyl_process.planning.validation import raise_for_errors, validate_plan
from vinyl_process.signal_ops import EPS, amplitude_to_db

logger = get_logger(__name__)
MANIFEST_NAME = "manifest.json"


def execute_plan(
    plan: ProcessingPlan,
    output_dir: str | Path,
    *,
    source_path: str | Path | None = None,
    plan_path: str | Path | None = None,
    plan_digest: str = "",
    verify_source: bool = True,
    overwrite: bool = False,
) -> ExecutionManifest:
    """Execute ``plan`` into ``output_dir`` and return the manifest."""
    return _Execution(
        plan=plan,
        output_dir=Path(output_dir),
        source_path=Path(source_path or plan.source.path),
        plan_path=Path(plan_path) if plan_path else None,
        plan_digest=plan_digest,
        verify_source=verify_source,
        overwrite=overwrite,
    ).run()


class _Execution:
    """One run. Holds the bookkeeping so the stage methods stay readable."""

    def __init__(
        self,
        *,
        plan: ProcessingPlan,
        output_dir: Path,
        source_path: Path,
        plan_path: Path | None,
        plan_digest: str,
        verify_source: bool,
        overwrite: bool,
    ) -> None:
        self.plan = plan
        self.output_dir = output_dir
        self.source_path = source_path
        self.plan_path = plan_path
        self.plan_digest = plan_digest
        self.verify_source = verify_source
        self.overwrite = overwrite
        self.stages: list[StageRecord] = []
        self.warnings: list[str] = []
        self.applied_gain_db: float | None = None

    # ------------------------------------------------------------------ #
    def run(self) -> ExecutionManifest:
        started_at = _now()
        findings = validate_plan(
            self.plan, audio_path=self.source_path, check_digest=self.verify_source
        )
        raise_for_errors(findings)
        for finding in findings:
            if finding.severity == "warning":
                self.warnings.append(str(finding))
                logger.warning("%s", finding)

        if not self.verify_source:
            self.warnings.append("source digest verification was disabled for this run")

        audio = load_audio(self.source_path)
        tracks = self._tracks(audio)
        buffers = self._split(audio, tracks)
        buffers = self._declick(buffers)
        buffers = self._normalize(buffers)
        buffers = self._resample(buffers)
        outputs = self._export(tracks, buffers)

        source = source_info_for(self.source_path)
        manifest = ExecutionManifest(
            generated_by=f"vinyl-process {__version__}",
            run_key=digest_json({"source": source.sha256, "plan": self.plan_digest}),
            source=source,
            plan=DocumentRef(
                path=str(self.plan_path) if self.plan_path else "", sha256=self.plan_digest
            ),
            stages=self.stages,
            applied_gain_db=self.applied_gain_db,
            outputs=outputs,
            environment=_environment(),
            started_at=started_at,
            completed_at=_now(),
            warnings=self.warnings,
        )
        manifest_path = self.output_dir / MANIFEST_NAME
        manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        logger.info("wrote %s", manifest_path)
        return manifest

    # ------------------------------------------------------------------ #
    def _tracks(self, audio: AudioBuffer) -> list[TrackBoundary]:
        if self.plan.split.enabled:
            return list(self.plan.split.tracks)
        return [TrackBoundary(index=1, start_sample=0, end_sample=audio.num_frames)]

    def _split(self, audio: AudioBuffer, tracks: list[TrackBoundary]) -> list[AudioBuffer]:
        if not self.plan.split.enabled:
            self._record("split", "skipped", detail="split disabled; the source is one track")
            return [audio]
        engine = self._engine(self.plan.split.engine, "split")
        self._record("split", "applied", engine=engine, section=self.plan.split)
        return engine.split(audio, tracks)

    def _declick(self, buffers: list[AudioBuffer]) -> list[AudioBuffer]:
        if not self.plan.declick.enabled:
            self._record("declick", "skipped", detail="declick disabled")
            return buffers
        engine = self._engine(self.plan.declick.engine, "declick")
        self._record(
            "declick",
            "applied",
            engine=engine,
            section=self.plan.declick,
            detail=f"algorithm={self.plan.declick.algorithm}",
        )
        return [engine.declick(buffer, self.plan.declick) for buffer in buffers]

    def _normalize(self, buffers: list[AudioBuffer]) -> list[AudioBuffer]:
        normalize = self.plan.normalize
        if not normalize.enabled or normalize.mode == "none":
            self._record("normalize", "skipped", detail=f"mode={normalize.mode}")
            return buffers

        engine = self._engine(normalize.engine, "gain")
        target = normalize.target_db

        if normalize.mode == "album_peak":
            peak = max(float(np.max(np.abs(buffer.samples))) for buffer in buffers)
            gain = target - float(amplitude_to_db(peak))
            return self._apply_album_gain(engine, buffers, gain, "album_peak")

        if normalize.mode == "album_rms":
            energy = sum(float(np.sum(buffer.samples**2)) for buffer in buffers)
            count = sum(buffer.samples.size for buffer in buffers)
            rms_db = float(amplitude_to_db(np.sqrt(energy / max(count, 1) + EPS)))
            return self._apply_album_gain(engine, buffers, target - rms_db, "album_rms")

        # track_peak: permitted by the contract, discouraged by the skill, because
        # it destroys the relative dynamics the pressing was mastered with.
        gains = [
            target - float(amplitude_to_db(np.max(np.abs(buffer.samples)))) for buffer in buffers
        ]
        self._record(
            "normalize",
            "applied",
            engine=engine,
            section=normalize,
            detail="mode=track_peak gains_db=" + ", ".join(f"{gain:+.3f}" for gain in gains),
        )
        return [
            engine.apply_gain(buffer, gain) for buffer, gain in zip(buffers, gains, strict=True)
        ]

    def _apply_album_gain(
        self, engine: DspEngine, buffers: list[AudioBuffer], gain_db: float, mode: str
    ) -> list[AudioBuffer]:
        self.applied_gain_db = round(gain_db, 4)
        self._record(
            "normalize",
            "applied",
            engine=engine,
            section=self.plan.normalize,
            detail=f"mode={mode} gain_db={self.applied_gain_db:+.4f}",
        )
        return [engine.apply_gain(buffer, gain_db) for buffer in buffers]

    def _resample(self, buffers: list[AudioBuffer]) -> list[AudioBuffer]:
        target = self.plan.export.sample_rate
        if target is None or not buffers or target == buffers[0].sample_rate:
            self._record("resample", "skipped", detail="export keeps the source sample rate")
            return buffers
        source_rate = buffers[0].sample_rate
        divisor = int(np.gcd(target, source_rate))
        up, down = target // divisor, source_rate // divisor
        self._record(
            "resample",
            "applied",
            detail=f"polyphase {source_rate} -> {target} Hz (up={up}, down={down})",
        )
        return [
            AudioBuffer(
                np.ascontiguousarray(
                    resample_poly(buffer.samples, up, down, axis=0), dtype=np.float64
                ),
                target,
            )
            for buffer in buffers
        ]

    def _export(self, tracks: list[TrackBoundary], buffers: list[AudioBuffer]) -> list[OutputFile]:
        export = self.plan.export
        self.output_dir.mkdir(parents=True, exist_ok=True)
        tag_stage_used = False
        outputs: list[OutputFile] = []

        for track, buffer in zip(tracks, buffers, strict=True):
            path = self.output_dir / track_filename(self.plan, track.index)
            if path.exists() and not self.overwrite:
                raise ExecutionError(
                    f"{path} already exists; pass overwrite=True (CLI: --overwrite) to replace it"
                )
            save_audio(
                path,
                buffer,
                export.format,
                export.bit_depth,
                dither=export.dither,
                dither_seed=export.dither_seed,
            )

            tagged = False
            if self.plan.metadata.enabled and export.write_tags:
                if path.suffix.lower() in SUPPORTED_SUFFIXES:
                    apply_tags(path, self.plan.metadata, track.index, len(tracks))
                    tagged = True
                    tag_stage_used = True
                else:  # pragma: no cover - guarded by the export format literal
                    self.warnings.append(f"tagging unsupported for {path.suffix} files")

            outputs.append(
                OutputFile(
                    track_index=track.index,
                    path=str(path),
                    sha256=digest_file(path),
                    bytes=path.stat().st_size,
                    num_samples=buffer.num_frames,
                    sample_rate=buffer.sample_rate,
                    duration_seconds=round(buffer.duration_seconds, 3),
                    source_start_sample=track.start_sample,
                    source_end_sample=track.end_sample,
                    tagged=tagged,
                )
            )
            logger.info("exported %s", path.name)

        self._record(
            "export",
            "applied",
            section=export,
            detail=f"{export.format}/{export.bit_depth}-bit, dither={export.dither}",
        )
        self._record(
            "metadata",
            "applied" if tag_stage_used else "skipped",
            section=self.plan.metadata,
            detail="tags written after audio processing" if tag_stage_used else "tagging disabled",
        )
        return outputs

    # ------------------------------------------------------------------ #
    def _engine(self, name: str, capability: Capability) -> DspEngine:
        engine = get_engine(name)
        engine.require(capability)
        return engine

    def _record(
        self,
        stage: StageName,
        status: StageStatus,
        *,
        engine: DspEngine | None = None,
        section: ContractModel | None = None,
        detail: str = "",
    ) -> None:
        params_digest = (
            digest_json(section.model_dump(mode="json")) if section is not None else None
        )
        self.stages.append(
            StageRecord(
                stage=stage,
                status=status,
                engine=engine.name if engine else None,
                engine_version=engine.version() if engine else None,
                params_digest=params_digest,
                detail=detail,
            )
        )


def _environment() -> dict[str, str]:
    """Versions that could conceivably change output bytes."""
    import mutagen
    import scipy
    import soundfile

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "soundfile": soundfile.__version__,
        "libsndfile": soundfile.__libsndfile_version__,
        "mutagen": mutagen.version_string,
    }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")

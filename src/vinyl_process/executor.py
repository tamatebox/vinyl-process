"""Plan executor: runs a ``ProcessingPlan`` end to end, deterministically.

Two phases. **Before the cuts**, on the whole side:
``prefilter -> declick -> decrackle -> mono_merge -> speed``. **After them**,
per track:
``split -> normalize -> resample -> export -> tag -> manifest``.

The pre-split order is practice's: discrete defects before continuous ones.

The pre-split phase exists because restoration practice repairs discrete defects
on the whole side and splits afterwards, and because anything that needs a
reference to the medium's own unmodulated groove — the lead-in, the run-out, an
inter-track gap — can only see one before the split discards all three. See
``docs/adr/0012-the-executor-has-a-pre-split-phase.md``.

Every subjective value comes from the plan. This module performs only the
arithmetic the plan implies, and it deliberately never reads ``analysis.json``:
if the executor needed the measurements to decide something, that something would
be a decision, and decisions belong to the planning skills.

The manifest it writes is the receipt: source and plan digests, the engine and
version that ran each stage, a digest of each stage's parameters, and the digest
of every file produced.
"""

from __future__ import annotations

import math
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import assert_never

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
from vinyl_process.signal_ops import (
    EPS,
    amplitude_to_db,
    gated_rms_of_blocks,
    level_matched_mono_merge,
    loudness_block_powers,
    loudness_of_blocks,
    map_sample_position,
    rms_blocks,
    true_peak,
)

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
    manifest_name: str = MANIFEST_NAME,
) -> ExecutionManifest:
    """Execute ``plan`` into ``output_dir`` and return the manifest.

    ``manifest_name`` matters for a two-sided record: both sides export into one
    album directory, and each run needs its own receipt.
    """
    return _Execution(
        plan=plan,
        output_dir=Path(output_dir),
        source_path=Path(source_path or plan.source.path),
        plan_path=Path(plan_path) if plan_path else None,
        plan_digest=plan_digest,
        verify_source=verify_source,
        overwrite=overwrite,
        manifest_name=manifest_name,
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
        manifest_name: str = MANIFEST_NAME,
    ) -> None:
        self.plan = plan
        self.output_dir = output_dir
        self.source_path = source_path
        self.plan_path = plan_path
        self.plan_digest = plan_digest
        self.verify_source = verify_source
        self.overwrite = overwrite
        self.manifest_name = manifest_name
        self.stages: list[StageRecord] = []
        self.warnings: list[str] = []
        self.applied_gain_db: float | None = None
        self.applied_track_gains_db: list[float] | None = None
        self.applied_true_peak_db: float | None = None
        self.time_ratio: float = 1.0
        """How the pre-split phase rescaled time, for mapping plan positions."""

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
        # Pre-split phase: the whole side, one buffer.
        audio = self._prefilter(audio)
        audio = self._declick(audio)
        audio = self._decrackle(audio)
        audio = self._mono_merge(audio)
        audio = self._speed(audio)
        # Post-split phase: one buffer per track.
        tracks = self._tracks(audio)
        buffers = self._split(audio, tracks)
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
            applied_track_gains_db=self.applied_track_gains_db,
            applied_true_peak_db=self.applied_true_peak_db,
            outputs=outputs,
            environment=_environment(),
            started_at=started_at,
            completed_at=_now(),
            warnings=self.warnings,
        )
        manifest_path = self.output_dir / self.manifest_name
        if manifest_path.exists() and not self.overwrite:
            raise ExecutionError(
                f"{manifest_path} already exists; pass overwrite=True (CLI: --overwrite), "
                "or give this run its own --manifest name"
            )
        manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        logger.info("wrote %s", manifest_path)
        return manifest

    # ------------------------------------------------------------------ #
    def _tracks(self, audio: AudioBuffer) -> list[TrackBoundary]:
        """The plan's boundaries, as the plan states them: source sample indices.

        These are what the manifest reports and what a reader compares against
        ``analysis.json``. Where the pre-split phase rescaled time, the *cut*
        happens somewhere else — see :meth:`_cut_positions`.
        """
        if self.plan.split.enabled:
            return list(self.plan.split.tracks)
        source_frames = round(audio.num_frames / self.time_ratio) or audio.num_frames
        return [TrackBoundary(index=1, start_sample=0, end_sample=source_frames)]

    def _cut_positions(self, track: TrackBoundary, frames: int) -> TrackBoundary:
        """``track`` mapped from the source timeline into the buffer's own.

        A no-op unless a pre-split stage rescaled time, which today only ``speed``
        does. The fades are in milliseconds and so need no mapping: a 250 ms fade
        is 250 ms of the audio that ships.
        """
        if self.time_ratio == 1.0:
            return track
        return track.model_copy(
            update={
                "start_sample": map_sample_position(track.start_sample, self.time_ratio, frames),
                "end_sample": map_sample_position(track.end_sample, self.time_ratio, frames),
            }
        )

    def _prefilter(self, audio: AudioBuffer) -> AudioBuffer:
        prefilter = self.plan.prefilter
        if not prefilter.enabled:
            self._record("prefilter", "skipped", detail="prefilter disabled")
            return audio
        if not prefilter.dc_block and prefilter.highpass_hz is None:
            # Enabled with nothing switched on is a plan that says it will act and
            # then does not. Say so in the receipt rather than reporting "applied".
            self._record(
                "prefilter",
                "skipped",
                detail="prefilter enabled but neither dc_block nor highpass_hz is set",
            )
            self.warnings.append(
                "prefilter is enabled but asks for nothing: dc_block is false and "
                "highpass_hz is null, so the audio passed through untouched"
            )
            return audio
        engine = self._engine(prefilter.engine, "prefilter")
        parts = []
        if prefilter.dc_block:
            parts.append("dc_block")
        if prefilter.highpass_hz is not None:
            parts.append(
                f"highpass={prefilter.highpass_hz:g} Hz @ "
                f"{prefilter.highpass_rolloff_db_per_octave} dB/oct"
            )
        self._record(
            "prefilter", "applied", engine=engine, section=prefilter, detail=" ".join(parts)
        )
        return engine.prefilter(audio, prefilter)

    def _split(self, audio: AudioBuffer, tracks: list[TrackBoundary]) -> list[AudioBuffer]:
        if not self.plan.split.enabled:
            self._record("split", "skipped", detail="split disabled; the source is one track")
            return [audio]
        engine = self._engine(self.plan.split.engine, "split")
        detail = ""
        if self.time_ratio != 1.0:
            detail = (
                f"cut positions mapped from the source timeline by x{self.time_ratio:.6f} "
                "(a pre-split stage rescaled time; the plan's positions are unchanged)"
            )
        self._record("split", "applied", engine=engine, section=self.plan.split, detail=detail)
        mapped = [self._cut_positions(track, audio.num_frames) for track in tracks]
        return engine.split(audio, mapped)

    def _declick(self, audio: AudioBuffer) -> AudioBuffer:
        """Repair the whole side, before the cuts.

        Two properties follow from the position, and both are the reason for it.
        The detector's 40 ms context window is never truncated at a track edge,
        and it never sees the fades — ``split`` applies those, so under the old
        ordering repair worked on ramped material, which biases an energy ratio
        *towards missing* clicks exactly in the bare-surface margins where a
        record's clicks are densest. It also repairs lead-in, run-out and gap
        material that the cuts then discard: wasted arithmetic, not wrong output.
        """
        if not self.plan.declick.enabled:
            self._record("declick", "skipped", detail="declick disabled")
            return audio
        engine = self._engine(self.plan.declick.engine, "declick")
        return self._repaired("declick", audio, engine.declick(audio, self.plan.declick), engine)

    def _decrackle(self, audio: AudioBuffer) -> AudioBuffer:
        """Repair the crackle bed, after ``declick`` and still before the cuts.

        Discrete defects before continuous ones, which is also the order that
        keeps the two from fighting: ``declick`` bridges the wide events first, so
        this stage's per-sample statistic is not looking at their edges.
        """
        if not self.plan.decrackle.enabled:
            self._record("decrackle", "skipped", detail="decrackle disabled")
            return audio
        engine = self._engine(self.plan.decrackle.engine, "decrackle")
        return self._repaired(
            "decrackle", audio, engine.decrackle(audio, self.plan.decrackle), engine
        )

    def _mono_merge(self, audio: AudioBuffer) -> AudioBuffer:
        """Fold the two groove walls, last of the pre-split stages.

        Last because the reference repairs the walls independently and merges
        afterwards, and warns against merging "at any of the intermediate stages"
        when a further repair pass follows. Here there is no further pass, so this
        is the end of the phase.
        """
        merge = self.plan.mono_merge
        if not merge.enabled:
            self._record("mono_merge", "skipped", detail="mono_merge disabled")
            return audio
        if audio.num_channels < 2:
            self._record(
                "mono_merge",
                "skipped",
                detail=f"source has {audio.num_channels} channel(s); nothing to merge",
            )
            self.warnings.append(
                "mono_merge is enabled but the source is not stereo, so there are no two "
                "groove walls to fold; the audio passed through untouched"
            )
            return audio
        engine = self._engine(merge.engine, "mono_merge")
        detail = f"strategy={merge.strategy}"
        if merge.strategy == "level_matched":
            # Report how hard the level tracker worked. A wide span is the signature
            # of a badly asymmetric transfer, or of the tracker following damage,
            # and neither should have to be discovered by listening.
            _merged, low, high = level_matched_mono_merge(
                audio.samples, audio.sample_rate, merge.level_window_seconds
            )
            detail += (
                f" window={merge.level_window_seconds:g}s "
                f"gain={float(amplitude_to_db(low)):+.2f}..{float(amplitude_to_db(high)):+.2f} dB"
            )
        self._record("mono_merge", "applied", engine=engine, section=merge, detail=detail)
        return engine.mono_merge(audio, merge)

    def _speed(self, audio: AudioBuffer) -> AudioBuffer:
        """Correct the replay speed, last of the pre-split stages.

        Last on purpose. Every repair stage ahead of it works on the transfer's
        own samples, so the parameters chosen against ``analysis.json`` still
        describe what the engine sees, and nothing is repaired on interpolated
        audio. Only the cut sees the corrected timeline.

        It is the first stage that changes the *length* of the buffer, which makes
        a plan position and the sample to cut at two different things. The plan's
        positions stay indices into the source — ``self.time_ratio`` is how the
        executor maps them, and the manifest still reports the source index. See
        ``docs/adr/0016-a-pre-split-stage-may-remap-time.md``.
        """
        speed = self.plan.speed
        if not speed.enabled:
            self._record("speed", "skipped", detail="speed disabled")
            return audio
        ratio = speed.ratio
        if ratio is None:
            raise ExecutionError(
                "speed is enabled but played_rpm and intended_rpm are not both set"
            )
        engine = self._engine(speed.engine, "speed")
        corrected = engine.change_speed(audio, speed)
        # The realised ratio, not the requested one: the resampler works on a
        # rational, and the receipt should say what actually happened.
        realised = corrected.num_frames / max(audio.num_frames, 1)
        self.time_ratio = realised
        self._record(
            "speed",
            "applied",
            engine=engine,
            section=speed,
            detail=(
                f"{speed.played_rpm:g} -> {speed.intended_rpm:g} rpm "
                f"(x{ratio:.6f}); {audio.num_frames} -> {corrected.num_frames} frames, "
                f"pitch {-1200 * math.log2(ratio):+.1f} cents"
            ),
        )
        return corrected

    def _repaired(
        self,
        stage: StageName,
        before: AudioBuffer,
        after: AudioBuffer,
        engine: DspEngine,
    ) -> AudioBuffer:
        """Record a repair stage, with **how much of the audio it changed**.

        The practitioner benchmark for repair is a fraction of samples — 1 in 200
        is "suspicious", 1 in 1000-2000 the typical floor (ClickRepair 3.9;
        ``plan-declick`` carries the citation). That figure used to be obtainable
        only by diffing two rendered directories, which meant it was usually not
        obtained at all, and a setting an order of magnitude below the band was
        chosen twice on one record without anyone noticing.

        The executor holds both buffers, so the exact count is arithmetic rather
        than a decision, and it belongs in the receipt where the person deciding
        will see it.
        """
        section = getattr(self.plan, stage)
        changed = int(np.count_nonzero(np.any(after.samples != before.samples, axis=1)))
        total = max(after.num_frames, 1)
        rate = f"1 in {total // changed}" if changed else "nothing changed"
        self._record(
            stage,
            "applied",
            engine=engine,
            section=section,
            detail=(
                f"algorithm={section.algorithm} (whole side, pre-split); "
                f"repaired {changed} of {total} samples ({rate})"
            ),
        )
        return after

    def _normalize(self, buffers: list[AudioBuffer]) -> list[AudioBuffer]:
        normalize = self.plan.normalize
        if not normalize.enabled or normalize.mode == "none":
            self._record("normalize", "skipped", detail=f"mode={normalize.mode}")
            return buffers

        engine = self._engine(normalize.engine, "gain")
        target = normalize.target_db
        mode = normalize.mode

        if mode == "track_peak":
            # Permitted by the contract, discouraged by the skill, because it
            # destroys the relative dynamics the pressing was mastered with.
            gains = [
                round(
                    self._capped(
                        target - float(amplitude_to_db(np.max(np.abs(buffer.samples)))), [buffer]
                    ),
                    4,
                )
                for buffer in buffers
            ]
            self.applied_track_gains_db = gains
            self._record(
                "normalize",
                "applied",
                engine=engine,
                section=normalize,
                detail="mode=track_peak gains_db=" + ", ".join(f"{gain:+.4f}" for gain in gains),
            )
            return [
                engine.apply_gain(buffer, gain) for buffer, gain in zip(buffers, gains, strict=True)
            ]

        if mode == "album_peak":
            peak = max((float(np.max(np.abs(b.samples))) for b in buffers), default=0.0)
            gain = target - float(amplitude_to_db(peak))
        elif mode == "album_gated_rms":
            # Pooling every track's blocks before gating is ReplayGain's album
            # rule: the album is measured as one continuous piece of programme.
            blocks = [rms_blocks(b.samples, b.sample_rate) for b in buffers]
            pooled = np.concatenate(blocks) if blocks else np.zeros(0)
            gain = target - float(amplitude_to_db(gated_rms_of_blocks(pooled)))
        elif mode == "album_lufs":
            # BS.1770's own album rule, and the same pooling as album_gated_rms:
            # every track's gating blocks go into one set before either gate, so
            # the album is measured as one continuous piece of programme. The
            # difference is the K-weighting, which is what makes the figure a
            # loudness in LUFS rather than a level in dBFS.
            powers = [loudness_block_powers(b.samples, b.sample_rate) for b in buffers]
            pooled_powers = np.concatenate(powers) if powers else np.zeros(0)
            gain = target - loudness_of_blocks(pooled_powers)
        elif mode == "album_rms":
            energy = sum(float(np.sum(buffer.samples**2)) for buffer in buffers)
            count = sum(buffer.samples.size for buffer in buffers)
            gain = target - float(amplitude_to_db(np.sqrt(energy / max(count, 1) + EPS)))
        else:
            # A new mode is a new measurement, never a fall-through into this
            # one: mypy fails the build until the branch exists.
            assert_never(mode)

        return self._apply_album_gain(engine, buffers, self._capped(gain, buffers), mode)

    def _capped(self, gain_db: float, buffers: list[AudioBuffer]) -> float:
        """``gain_db``, reduced if it would carry the true peak past the ceiling.

        Hitting a level target says nothing about where the peaks land, so an RMS
        mode without this guard can drive the export straight into
        ``save_audio``'s clip. The ceiling holds against the *true* peak because
        that bounds the sample peak of any later resampling too.
        """
        ceiling = self.plan.normalize.peak_ceiling_db
        if ceiling is None or not buffers:
            return gain_db
        reconstructed = max(true_peak(buffer.samples) for buffer in buffers)
        headroom = ceiling - float(amplitude_to_db(reconstructed))
        if gain_db <= headroom:
            return gain_db
        self.warnings.append(
            f"normalize: {self.plan.normalize.mode} asked for {gain_db:+.4f} dB but "
            f"peak_ceiling_db {ceiling:+.2f} dBTP allows only {headroom:+.4f} dB; "
            "the gain was capped and the target level was not reached"
        )
        return headroom

    def _apply_album_gain(
        self, engine: DspEngine, buffers: list[AudioBuffer], gain_db: float, mode: str
    ) -> list[AudioBuffer]:
        # Record and apply the *same* rounded value, so the manifest describes
        # exactly what was done rather than something 1e-15 away from it.
        gain = round(gain_db, 4)
        self.applied_gain_db = gain
        self._record(
            "normalize",
            "applied",
            engine=engine,
            section=self.plan.normalize,
            detail=f"mode={mode} gain_db={gain:+.4f}",
        )
        return [engine.apply_gain(buffer, gain) for buffer in buffers]

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

    def _measure_export(self, track: TrackBoundary, buffer: AudioBuffer) -> None:
        """Record the true peak of what is about to be written, and say so if it
        will not fit.

        ``save_audio`` clamps to full scale, which is the right thing for it to
        do and the wrong thing to do silently: without this the album could come
        out clipped with nothing in the receipt to show it. Measured here rather
        than in ``_normalize`` because resampling comes in between and turns
        inter-sample peaks into real ones.
        """
        reconstructed = round(float(amplitude_to_db(true_peak(buffer.samples))), 4)
        self.applied_true_peak_db = (
            reconstructed
            if self.applied_true_peak_db is None
            else max(self.applied_true_peak_db, reconstructed)
        )
        over = int(np.count_nonzero(np.abs(buffer.samples) > 1.0))
        if over:
            peak_db = float(amplitude_to_db(np.max(np.abs(buffer.samples))))
            ceiling = self.plan.normalize.peak_ceiling_db
            self.warnings.append(
                f"track {track.index} clips: {over} sample(s) past full scale, peaking at "
                f"{peak_db:+.2f} dBFS, clamped on write; normalize.peak_ceiling_db "
                + ("is not set" if ceiling is None else f"is {ceiling:+.2f} dBTP")
            )

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
            self._measure_export(track, buffer)
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

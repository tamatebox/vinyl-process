"""FFmpeg-backed engine — proof that engines are interchangeable.

``declick`` maps to ffmpeg's ``adeclick`` filter and ``gain`` to ``volume``.
Deterministic for a fixed ffmpeg build, whose version string the manifest
records. ``split`` is deliberately not offered: sample-exact cutting is what the
native engine is for, and the executor is happy to mix engines across stages.

Parameter mapping (deterministic and documented, which is what keeps it out of
"decision" territory):

* ``threshold`` -> ``adeclick:t``. Each engine interprets ``threshold`` on its
  own scale; for ``adeclick`` that is its native 1..100 scale, not sigmas.
* ``max_click_width_ms`` -> ``adeclick:w``, the analysis window, clamped to the
  filter's supported 10..100 ms and never narrower than four click widths.
* ``params`` overrides any of ``window_ms``, ``threshold``, ``overlap``,
  ``ar_order``, ``burst_fusion``, ``method`` explicitly.
* ``strength`` has no equivalent: rather than silently dropping a decision the
  plan made, anything below 1.0 is rejected.

``gain`` runs with ``precision=double`` so it matches the native engine to double
rounding. ``adeclick`` has no such switch: it is deterministic for a fixed ffmpeg
build, but its output is its own — which is exactly why the plan pins the engine
by name and the manifest records the version that ran.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from vinyl_process.audio import AudioBuffer, load_audio, save_audio_float64
from vinyl_process.dsp.base import Capability, DspEngine
from vinyl_process.errors import EngineUnavailableError, ExecutionError
from vinyl_process.models.plan import DeclickPlan

ALGORITHMS = frozenset({"adeclick"})


@lru_cache(maxsize=1)
def _ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


@lru_cache(maxsize=1)
def _ffmpeg_version() -> str:
    binary = _ffmpeg_path()
    if binary is None:
        return "ffmpeg (not found)"
    try:
        result = subprocess.run(
            [binary, "-version"], capture_output=True, text=True, check=True, timeout=30
        )
    except (subprocess.SubprocessError, OSError) as exc:  # pragma: no cover - env specific
        return f"ffmpeg (version unavailable: {exc})"
    return result.stdout.splitlines()[0].strip()


class FfmpegEngine(DspEngine):
    name = "ffmpeg"

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({"declick", "gain"})

    def is_available(self) -> bool:
        return _ffmpeg_path() is not None

    def version(self) -> str:
        return _ffmpeg_version()

    def declick(self, audio: AudioBuffer, plan: DeclickPlan) -> AudioBuffer:
        if plan.algorithm not in ALGORITHMS:
            raise ExecutionError(
                f"engine 'ffmpeg' does not implement algorithm {plan.algorithm!r}; "
                f"available: {sorted(ALGORITHMS)}"
            )
        if plan.strength < 1.0:
            raise ExecutionError(
                "engine 'ffmpeg' cannot honour declick.strength < 1.0 (adeclick has no "
                "strength control); use engine 'native' or set strength to 1.0"
            )
        options = {
            "w": _clamp(
                plan.params.get("window_ms", max(10.0, 4.0 * plan.max_click_width_ms)), 10.0, 100.0
            ),
            "t": _clamp(plan.params.get("threshold", plan.threshold), 1.0, 100.0),
            "o": _clamp(plan.params.get("overlap", 75.0), 50.0, 95.0),
            "a": _clamp(plan.params.get("ar_order", 2.0), 0.0, 25.0),
            "b": _clamp(plan.params.get("burst_fusion", 2.0), 0.0, 10.0),
            "m": str(plan.params.get("method", "add")),
        }
        spec = "adeclick=" + ":".join(f"{key}={value}" for key, value in options.items())
        return self._run_filter(audio, spec)

    def apply_gain(self, audio: AudioBuffer, gain_db: float) -> AudioBuffer:
        # ``precision=double`` matters: the filter defaults to float internally,
        # which leaves ~1e-7 of error against the native engine. With it, both
        # engines agree to double rounding, so an album can be re-cut with either.
        return self._run_filter(audio, f"volume={gain_db}dB:precision=double")

    def _run_filter(self, audio: AudioBuffer, filter_spec: str) -> AudioBuffer:
        binary = _ffmpeg_path()
        if binary is None:
            raise EngineUnavailableError("ffmpeg binary not found on PATH")
        with tempfile.TemporaryDirectory(prefix="vinyl-ffmpeg-") as tmp:
            source = Path(tmp) / "in.wav"
            target = Path(tmp) / "out.wav"
            # float64 WAV in and out, so the round-trip itself is lossless.
            save_audio_float64(source, audio)
            command = [
                binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source),
                "-af",
                filter_spec,
                "-c:a",
                "pcm_f64le",
                str(target),
            ]
            try:
                subprocess.run(command, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as exc:
                raise ExecutionError(
                    f"ffmpeg failed for filter {filter_spec!r}: {exc.stderr.strip()}"
                ) from exc
            return load_audio(target)


def _clamp(value: object, low: float, high: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"ffmpeg declick parameter must be numeric, got {value!r}") from exc
    return min(high, max(low, number))

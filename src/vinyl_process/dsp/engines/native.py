"""Pure numpy/scipy engine — the reproducibility baseline.

No external binaries, so its output depends only on the pinned numpy/scipy
versions. Every capability is implemented here; other engines may be faster or
sound better, but this one is always available and always deterministic.
"""

from __future__ import annotations

import numpy as np

from vinyl_process import __version__
from vinyl_process.audio import AudioBuffer
from vinyl_process.dsp.base import Capability, DspEngine
from vinyl_process.errors import ExecutionError
from vinyl_process.models.plan import DeclickPlan, TrackBoundary
from vinyl_process.signal_ops import apply_fades, click_events, repair_clicks

ALGORITHMS = frozenset({"mad_interpolate"})
"""``mad_interpolate``: detect clicks as robust-sigma outliers of a high-passed,
median-detrended signal, then bridge each one with cubic Hermite interpolation.
``threshold`` is in robust-sigma (MAD) multiples."""


class NativeEngine(DspEngine):
    name = "native"

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({"split", "declick", "gain"})

    def version(self) -> str:
        return f"native {__version__} (numpy {np.__version__})"

    def split(self, audio: AudioBuffer, tracks: list[TrackBoundary]) -> list[AudioBuffer]:
        """Sample-exact cuts with the fades the plan asked for."""
        pieces = []
        for track in tracks:
            end = min(track.end_sample, audio.num_frames)
            if track.start_sample >= end:
                raise ExecutionError(
                    f"track {track.index}: start_sample {track.start_sample} is at or beyond "
                    f"the end of the source ({audio.num_frames} samples)"
                )
            piece = audio.slice(track.start_sample, end)
            if track.fade_in_ms or track.fade_out_ms:
                piece = piece.with_samples(
                    apply_fades(
                        piece.samples, piece.sample_rate, track.fade_in_ms, track.fade_out_ms
                    )
                )
            pieces.append(piece)
        return pieces

    def declick(self, audio: AudioBuffer, plan: DeclickPlan) -> AudioBuffer:
        if plan.algorithm not in ALGORITHMS:
            raise ExecutionError(
                f"engine 'native' does not implement algorithm {plan.algorithm!r}; "
                f"available: {sorted(ALGORITHMS)}"
            )
        highpass_hz = float(plan.params.get("highpass_hz", 3000.0))
        events = click_events(
            audio.mono(),
            audio.sample_rate,
            plan.threshold,
            plan.max_click_width_ms,
            highpass_hz=highpass_hz,
        )
        return audio.with_samples(repair_clicks(audio.samples, events, plan.strength))

    def apply_gain(self, audio: AudioBuffer, gain_db: float) -> AudioBuffer:
        return audio.with_samples(audio.samples * (10.0 ** (gain_db / 20.0)))

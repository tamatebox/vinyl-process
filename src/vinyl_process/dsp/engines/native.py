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
from vinyl_process.signal_ops import (
    apply_fades,
    click_events_block,
    repair_clicks,
    repair_clicks_ar,
    repair_clicks_linear,
)

ALGORITHMS = frozenset({"block_ratio"})
"""``block_ratio``: detect clicks where the energy of a click-width window exceeds
the energy of its neighbourhood by ``threshold`` times, then reconstruct each one
by autoregressive least squares (Janssen 1986). ``threshold`` is a **ratio, not a
sigma count**, and no one value suits two pressings — it comes from
``clicks.threshold_sweep``, per recording, and there is deliberately no
default. ``params`` accepts ``interpolator``
(``ar`` | ``hermite`` | ``linear``), ``detect_ms`` (0.2), ``context_ms`` (40.0),
``highpass_hz`` (3000), and ``ar_order`` / ``ar_iterations`` / ``ar_context``.

The id names the *detector*, because that is the half with evidence behind it.

What is established, on real audio and without synthetic damage:

- **The detector.** A single robust sigma is not a local statistic: handed the
  same 60 s in different chunk sizes, the robust-sigma detector this replaced
  moved its answer by up to 7.8x, while the energy ratio held to within 10%.
  Under the old statistic the analyzer (which sees a side) and this engine
  (which sees one track) described different events — measured once at 38 693
  clicks reported against 58 355 spans repaired. On a near-clean pressing used
  as a negative control it claimed 1082 events a minute while finding *none* in
  the inter-track gaps, where the surface is unmasked; the ratio found few and
  concentrated them in the gaps, twelve of which were confirmed audible by ear.
- **The bound on the repair.** Unbounded, the cubic bridged a 65-sample gap at
  twelve times the amplitude of its neighbourhood and three times the peak of the
  whole track — inside the width limit the plan had set. See ``repair_clicks``.

What is **not** established: which interpolator is better. Comparisons by SNR
against damage injected here were discarded as unsound — the material, the click
shapes and the amplitudes were all chosen by the same hand that chose the
algorithm. Nor is there a public benchmark to appeal to: the reference
implementation of this method notes that the uncorrupted original is unavailable
and falls back on listening. Hence ``interpolator`` is a parameter and not a
decision baked in here."""


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
        if plan.threshold is None:
            raise ExecutionError(
                "declick is enabled but no threshold is set. It is a decision, not a "
                "default: read clicks.threshold_sweep and choose a rung for this pressing"
            )
        events = click_events_block(
            audio.mono(),
            audio.sample_rate,
            plan.threshold,
            plan.max_click_width_ms,
            detect_ms=float(plan.params.get("detect_ms", 0.2)),
            context_ms=float(plan.params.get("context_ms", 40.0)),
            highpass_hz=float(plan.params.get("highpass_hz", 3000.0)),
        )
        interpolator = str(plan.params.get("interpolator", "ar"))
        if interpolator == "linear":
            return audio.with_samples(repair_clicks_linear(audio.samples, events, plan.strength))
        if interpolator == "hermite":
            return audio.with_samples(repair_clicks(audio.samples, events, plan.strength))
        if interpolator != "ar":
            raise ExecutionError(
                f"engine 'native' has no interpolator {interpolator!r}; "
                "available: ar, hermite, linear"
            )
        # Order and window are *derived*, not chosen: the published rule for this
        # interpolator ties both to the widest gap it must bridge (p = 3*Nmax + 2,
        # window = 8p) and Nmax is already in the plan as max_click_width_ms.
        # Converting a plan value into an engine's units is allowed when the
        # mapping is deterministic and documented; inventing the numbers is not,
        # and the ones that used to sit here were invented an order of magnitude
        # away from the rule.
        widest = max(1, round(plan.max_click_width_ms / 1000.0 * audio.sample_rate))
        order = int(plan.params.get("ar_order", 3 * widest + 2))
        return audio.with_samples(
            repair_clicks_ar(
                audio.samples,
                events,
                plan.strength,
                order=order,
                iterations=int(plan.params.get("ar_iterations", 2)),
                context=int(plan.params.get("ar_context", 8 * order)),
            )
        )

    def apply_gain(self, audio: AudioBuffer, gain_db: float) -> AudioBuffer:
        return audio.with_samples(audio.samples * (10.0 ** (gain_db / 20.0)))

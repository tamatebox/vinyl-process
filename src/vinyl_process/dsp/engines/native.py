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
from vinyl_process.models.plan import (
    DeclickPlan,
    DecracklePlan,
    MonoMergePlan,
    PrefilterPlan,
    TrackBoundary,
)
from vinyl_process.signal_ops import (
    apply_fades,
    click_events_block,
    confirm_clicks_sinusoidal,
    crackle_events_curvature,
    level_matched_mono_merge,
    remove_dc,
    repair_clicks,
    repair_clicks_ar,
    repair_clicks_linear,
    subsonic_highpass,
)

ALGORITHMS = frozenset({"block_ratio"})
CRACKLE_ALGORITHMS = frozenset({"curvature_ratio"})
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
        return frozenset({"prefilter", "split", "declick", "decrackle", "mono_merge", "gain"})

    def version(self) -> str:
        return f"native {__version__} (numpy {np.__version__})"

    def prefilter(self, audio: AudioBuffer, plan: PrefilterPlan) -> AudioBuffer:
        """DC removal then the subsonic high-pass, in that order.

        The order is not arbitrary: a DC offset is a step at the filter's input,
        and an IIR high-pass answers a step with a settling transient. Removing
        the mean first leaves the filter nothing to settle from.

        ``highpass_rolloff_db_per_octave`` becomes a Butterworth order by the
        documented identity ``order = rolloff / 6`` — a unit conversion, which an
        engine may perform, not a choice. The filter runs forward only so the
        delivered rolloff is the one the plan asked for; see
        ``signal_ops.subsonic_highpass``.
        """
        samples = audio.samples
        if plan.dc_block:
            samples = remove_dc(samples)
        if plan.highpass_hz is not None:
            samples = subsonic_highpass(
                samples,
                audio.sample_rate,
                plan.highpass_hz,
                plan.highpass_rolloff_db_per_octave // 6,
            )
        if samples is audio.samples:
            return audio
        return audio.with_samples(samples)

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
        # Alvarez, Mendez & Langwagen (DAFx 2004): discard candidates that a few
        # sinusoids already explain. Opt-in, because `confirm_k` is a decision and
        # a default here would be one taken for every record. With it the detector
        # can stay sensitive: raising a threshold until it stops firing on the
        # music also stops it finding quiet clicks, and this separates the two.
        confirm_k = plan.params.get("confirm_k")
        if confirm_k is not None:
            events = confirm_clicks_sinusoidal(
                audio.mono(),
                events,
                float(confirm_k),
                components=int(plan.params.get("confirm_components", 5)),
                margin=int(plan.params.get("confirm_margin", 50)),
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

    def decrackle(self, audio: AudioBuffer, plan: DecracklePlan) -> AudioBuffer:
        """Per-sample outlier repair for a bed of 1-3 sample events.

        Linear interpolation by default rather than AR, and that is not laziness:
        across one to three samples a straight line between the two survivors
        cannot leave the range they span, so it cannot diverge on any material,
        while an AR fit of order 11 (the derived rule for a 3-sample gap) would be
        estimating a model from a context far larger than the hole it fills. The
        interpolator stays a ``params`` choice because "which is best" is unsettled
        here for the same reason it is in ``declick``.
        """
        if plan.algorithm not in CRACKLE_ALGORITHMS:
            raise ExecutionError(
                f"engine 'native' does not implement algorithm {plan.algorithm!r}; "
                f"available: {sorted(CRACKLE_ALGORITHMS)}"
            )
        if plan.threshold is None:
            raise ExecutionError(
                "decrackle is enabled but no threshold is set. It is a decision, not a "
                "default: it is a curvature ratio, smaller is more aggressive, and the "
                "setting is held against the repair-rate band per pressing"
            )
        events = crackle_events_curvature(
            audio.mono(),
            plan.threshold,
            plan.max_event_width_samples,
            context_ms=float(plan.params.get("context_ms", 5.0)),
            sample_rate=audio.sample_rate,
        )
        interpolator = str(plan.params.get("interpolator", "linear"))
        if interpolator == "linear":
            return audio.with_samples(repair_clicks_linear(audio.samples, events, plan.strength))
        if interpolator == "hermite":
            return audio.with_samples(repair_clicks(audio.samples, events, plan.strength))
        raise ExecutionError(
            f"engine 'native' has no decrackle interpolator {interpolator!r}; "
            "available: linear, hermite"
        )

    def mono_merge(self, audio: AudioBuffer, plan: MonoMergePlan) -> AudioBuffer:
        """Fold the two groove walls onto one signal, written to both channels.

        Both channels, not one, because the reference keeps the file stereo — "the
        same data is written to both channels of the output file" — and because
        collapsing the channel count here would surprise every later stage.
        """
        if audio.num_channels < 2:
            # Already one wall's worth of data. Nothing to merge, and saying so is
            # better than silently duplicating a channel.
            return audio
        if plan.strategy in ("left", "right"):
            index = 0 if plan.strategy == "left" else 1
            wall = audio.samples[:, index : index + 1]
            return audio.with_samples(np.repeat(wall, audio.num_channels, axis=1))
        merged, _low, _high = level_matched_mono_merge(
            audio.samples, audio.sample_rate, plan.level_window_seconds
        )
        return audio.with_samples(np.repeat(merged, audio.num_channels, axis=1))

    def apply_gain(self, audio: AudioBuffer, gain_db: float) -> AudioBuffer:
        return audio.with_samples(audio.samples * (10.0 ** (gain_db / 20.0)))

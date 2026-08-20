# 0003 — The plan declares a normalization strategy; the executor computes the gain

**Status**: accepted

## Context

"DSP must never make subjective decisions" suggests the plan should carry the
exact gain in dB. But the gain depends on the peak *after* declicking, and
declicking is the stage immediately before. A skill that precomputed the gain
would have to predict the effect of the repair it just prescribed — or the plan
would have to be authored in two passes with a DSP run in between.

## Decision

The plan records the **strategy and target** (`mode: album_peak`,
`target_db: -1.0`). The executor measures the post-declick material and computes
the gain, then records the value it applied in `manifest.applied_gain_db`.

## Consequences

- The subjective part (album-wide versus per-track, and how much headroom) stays a
  decision in the plan; the objective part (arithmetic over the measured peak)
  stays in the executor.
- Determinism is unaffected: the computation is a pure function of the audio and
  the plan.
- The manifest is required to make the run auditable — the plan alone does not say
  what gain was applied. `verify` re-derives it and compares.
- `plan-normalize` is explicitly told not to precompute a gain.

# 0007 — A level target needs a true-peak ceiling

**Status**: accepted

## Context

`normalize.target_db` means two different things depending on the mode. For
`album_peak` it *is* the ceiling: the executor puts the sample peak exactly
there. For `album_rms` it is a level, and nothing in the plan or the executor said
anything about where the peaks then landed. A plan asking for −18 dB RMS on quiet
material got a large positive gain, `save_audio`'s `np.clip` clamped whatever came
out above full scale, and the manifest recorded a clean run. The album was
clipped and the receipt did not say so.

Sample peak is also the wrong quantity to hold a ceiling against. A meter reading
only the stored samples misses the inter-sample peaks a reconstruction filter puts
back, so material at −0.1 dBFS can reconstruct above 0 dBTP — and the executor
itself resamples *after* normalizing, which turns those peaks into real ones.
ITU-R BS.1770-4 measures the true peak by oversampling 4× first; every streaming
platform states its ceiling in dBTP for the same reason.

## Decision

`normalize.peak_ceiling_db` (dBTP, `None` by default) is a second, independent
decision the plan may carry: the highest true peak the album is allowed to reach.
When it is set, the executor computes the gain the mode asks for, measures the
4×-oversampled peak, and **reduces the gain** if the two disagree — recording a
warning that says the target level was not reached.

The ceiling holds against the true peak rather than the sample peak because the
true peak bounds the sample peak of *any* later resampling of the same material.
Enforcing it once, before the resampler, therefore also protects the export.

Independently of the ceiling, the executor now measures the true peak of what it
is about to write and records it as `manifest.applied_true_peak_db`, warning per
track when samples had to be clamped.

## Consequences

- Clipping is never silent again: with a ceiling it does not happen, and without
  one it appears in `manifest.warnings` and in `applied_true_peak_db`.
- The strategy/arithmetic split of [0003](0003-normalization-gain-is-computed-at-execution.md)
  is unchanged. *How loud* and *how much headroom* stay decisions in the plan; the
  executor still only measures and divides.
- Two decisions can now conflict, and the plan cannot say which wins. The
  executor resolves it one way — the ceiling always wins over the target — because
  a clipped album is a defect and a quiet one is a preference. The warning exists
  so the skill can see it happened and re-plan.
- `plan-normalize` must set a ceiling for every RMS mode; `lint` warns when it
  does not, and the warning reaches the executor's own findings too.
- `target_db` is still allowed to be `0.0`: the contract does not encode taste.
  `lint` reports `no-headroom` instead.
- Cost: one 4×-oversampled pass over the album per ceiling check and one per
  exported track. Small next to declicking, but not free.

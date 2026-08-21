# 0016 — A pre-split stage may remap time; plan positions do not move

**Status**: accepted

## Context

Every position in these contracts is an integer sample index into the **source**
recording ([0002](0002-sample-positions-are-integers.md)). `split.tracks[]` are,
`manifest.outputs[].source_start_sample` is, and `lint` checks cuts against
`source.num_samples`. That invariant is what lets a boundary be argued from
`analysis.json`, agreed at a checkpoint, and still mean the same thing a year
later.

`speed` is the first stage that breaks it. Correcting a transfer played at the
wrong speed is a resample: the buffer the executor cuts is no longer the same
length as the source. Sample 88 200 of the corrected audio is not sample 88 200 of
the recording.

The same question had already been raised, in a different guise, about a possible
`trim` stage — one that would drop the recorder's pre-roll before the needle
landed. Both are the same shape: **a pre-split stage that changes the mapping
between plan time and buffer time**, one by a scale and one by an offset.

Three ways out were available.

1. **Redefine plan positions** as indices into whatever the pre-split phase
   produced. Cheapest to implement and the worst: `split.tracks[]` would then mean
   something different depending on which earlier stages were enabled, and a
   boundary could no longer be compared against `analysis.json` at all.
2. **Put the stage after `split`.** Keeps the invariant, but resamples each track
   separately: every track edge gets the resampler's own transient, and a gapless
   side — where `plan-split` requires `end_sample == the next start_sample` so the
   tracks concatenate back sample for sample — acquires a seam at every join.
3. **Keep the invariant and map at the cut.**

## Decision

**Option 3. Plan positions stay indices into the source; the executor maps them
into the corrected timeline when it cuts.**

The executor carries one number, `time_ratio`, describing how the pre-split phase
rescaled time — 1.0 unless something changed it. `_cut_positions` maps a boundary
through it immediately before `native.split()`, and the manifest goes on reporting
the plan's own source indices in `source_start_sample` / `source_end_sample`. The
`split` stage record says when a mapping was applied and by how much, so it is in
the receipt rather than implicit.

This is a *unit conversion*, which the architecture already permits Python to
perform: deterministic, documented, and derived from a value the plan states
rather than from a judgement.

**`speed` is last of the pre-split stages.** Every repair — `prefilter`,
`declick`, `decrackle`, `mono_merge` — therefore works on the transfer's own
samples, so the parameters chosen against `analysis.json` still describe what the
engine sees, and nothing is repaired on interpolated audio.

**The general rule this establishes**: a pre-split stage may apply an affine map to
time. It may not change what a plan position means. A future `trim` would supply an
offset the same way `speed` supplies a scale, and would compose with it.

### Why the stage exists at all, given that practice says otherwise

IASA-TC04 5.2.5 is explicit that the fix belongs at replay: "it is imperative that
the disc be replayed for transfer as close to the original recording speed as is
possible", and a deliberate reduced-speed replay should be "coupled with a doubled
sample rate" at capture. This stage is therefore the **second-best** answer, and
`plan-speed` says so.

It earns its place on two grounds. A transfer that already happened cannot be
replayed differently without doing it again, and a resample is exact where a
re-transfer costs an afternoon. And the correction is a *fact to be recorded*: the
same section requires that "the chosen replay speed should be documented in
accompanying metadata. This is particularly important where any doubt remains as to
the actual recording speed" — which on shellac is nearly always, since "coarse
groove shellac discs were not recorded at precisely 78rpm". The section therefore
carries `played_rpm` and `intended_rpm` rather than a bare ratio: the pair *is* the
documentation, and the ratio is derived from it.

## Consequences

- `SCHEMA_VERSION` 3.6 → **3.7**, minor: optional and disabled by default.
- **A boundary agreed at the split checkpoint survives.** That is the whole point
  of the invariant, and `plan-speed`'s checkpoint is instructed to say so, because
  it is the thing a person will reasonably worry about.
- **`analysis.json` describes the uncorrected transfer**, and always will — the
  analyzer runs before any plan exists. Every figure quoted from it after this
  stage is enabled, durations above all, is in the old timeline. The skills have to
  name which timeline a number is in.
- **A gross correction is a warning, not a feature.** Above a semitone, `lint`
  reports `speed-correction-is-gross`: at that size every stage ahead of this one,
  and the analysis the plan was written from, saw the wrong spectrum. The
  100-cent line is this project's; the reasoning behind it is IASA's.
- **The rational grid is bounded, and the bound is not free.** `resample_poly`
  needs an integer up/down pair, so the ratio is approximated. Measured: at a
  denominator bound of 1000, a ratio of 1.00042 — 0.73 cents — rounds to **exactly
  1**, and the stage would have reported itself applied while changing nothing. The
  bound is 20 000, where the same ratio is exact to 8e-9 and a thirty-second stereo
  buffer resamples in 0.04 s. `resample_by_ratio` still refuses a ratio that
  collapses to unity, because no bound removes that possibility entirely.
- Correcting speed *and* resampling on export filters the audio twice. `lint`
  reports it as `speed-and-resample`; combining them into one operation would be
  faster and would make the receipt say less, so it is not done.
- **This codebase still cannot measure a speed deviation.** `periodicity`
  correlates at *configured* nominal periods (1.8 s, 1.3333 s) and reports how
  strongly each matches — it never searches for the period the platter actually
  ran at. So the deviation comes from outside: a strobe disc, a test record, a
  reference tone, or a judgement. `plan-speed` requires the method to be named, and
  refusing to guess is the honest default.

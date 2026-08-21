# 0021 — The trailing edge is measured by the platter, not the level

**Status**: accepted

## Context

Every boundary on a side is bracketed by music on both sides except one: the end
of the last track. Past it lies the run-out groove, which sits at the same level
as a quiet outro. That asymmetry is why the interior markers work and the trailing
one never has.

Two fields looked like they answered the question and both fail, in opposite
directions. Measured on the four sides of one 2xLP — third rank of this project's
evidence hierarchy, a measurement on a real transfer:

- **`boundaries.lead_out_start_sample` fires early.** It is where the level last
  crossed the silence threshold, so on a closing fade it fires mid-fade: 9.3 s
  early on side C and 5.0 s early on side D. Taken at face value it would have
  cut nine seconds off the end of *Blow Your Mind*. This was already a documented
  limitation, from a dub side where it landed 22 s early.
- **`silence.regions[-1].music_end_sample` fires late, and much worse.** Its
  reference is the region's own **minimum** plus 3 dB, and a trailing region
  routinely holds *two* floors: the run-out groove, and the needle lift after it.
  The lift then owns the minimum — on side D the region ran 775.0-807.7 s with the
  run-out between −45 and −62 dB and the lift at −87.8 dB, so the reference sat at
  −83.5 dB and no frame of the run-out ever reached it. The answer came back at
  807.0 s against a real music end near 780.0 s: **27 s late**, and it did that on
  three of the four sides. Side A escaped only because a tick split its lift into
  a separate region.

"Err long" was written into `_music_end` to protect a few seconds of faded surface
noise. It was never meant to license half a minute of run-out.

**Six formulations were written and measured before the one that shipped**, which
is the part worth recording. Three patched `_music_end`: a local reference (the
minimum of the following second) fires immediately on a slow fade, because the
25 s dB-linear fade in the test suite falls 2.7 dB per second — less than
`settle_margin_db` within the window, so a fade and a floor are locally
indistinguishable at those sizes. Truncating the region at a step down against
the median of everything after it fires at the start of any region that begins
mid-fade, which moved an **inter-track** gap on side A by 4.5 s. Requiring a
plateau before the step never fires at all, because a run-out is not flat within
3 dB — it wanders more than 10 dB between ticks. The condition that protects side
A and the condition that detects the other three cannot both hold at one margin.

Three more compared bands against a whole-file reference, and those failed for a
subtler reason: they worked, but only for parameters chosen after seeing the
answer. Across an 81-point grid the worst-case error moved between 0.2 s and
22.6 s, and a **1 s change in a smoothing window moved one side by 28 s**. A
parameter surface that steep is a fit to one record, which is exactly what this
project's rules forbid.

What made the hand derivation work was not the band comparison. It was that a
human had looked at `periodicity` first and chosen where to start searching.
Without that anchor, "every band has settled to the run-out's level" is also true
of every inter-track gap on the side.

## Decision

**A new analyzer, `run_out`, measures where the music stops, from `periodicity`
and `band_profile` read together.** The platter, not the level, separates a
run-out from a quiet outro:

- **`periodicity` supplies the anchor** — the last window whose own top
  autocorrelation peak beats the platter's revolution correlations by
  `programme_peak_factor`. That is the question the analyzer was built for, asked
  per window rather than against `programme_period_seconds`, and taking the *last*
  such window rather than the first surface-looking one is what stops a quiet
  mid-side passage ending the record early.
- **`band_profile` refines it** to the first frame at which every band has reached
  the run-out's own level, that level being the per-band **median** of the file's
  tail. A median rather than a minimum is precisely the fix: the needle lift is a
  small fraction of the tail, so it cannot set the reference — which is the
  mistake `silence` makes.

Across the four sides the pair landed within **0.6 s**. The one sensitive
parameter is `programme_peak_factor`, and its plateau is measured: every value
from **1.4 to 10.0** gave an identical answer on all four sides, with the cliff at
1.2. The default of 1.5 is a step off that cliff inside a plateau seven times
wider than itself. The other three parameters moved nothing across sweeps three
times wide.

**It is its own analyzer rather than a field on `boundaries`.** Adding
`periodicity` to that analyzer's `requires` would mean a periodicity failure costs
the candidate list too, and the candidates are what `boundaries` is for. As a
separate optional section it degrades only itself.

**Schema 3.7 → 3.8**, additive: an archived document without the section stays
valid, and a consumer that does not read it is unaffected.

## Consequences

- **`plan-split` prefers it and still checks it.** The evidence is one record, so
  the skill states that count, keeps the `periodicity` cross-check unconditional
  rather than only where the field is `null`, and prefers the longer cut where the
  two disagree. The detail lives in
  [references/surface-or-programme.md](../../.claude/skills/plan-split/references/surface-or-programme.md);
  `docs/processed-records.md` carries it as a **lead**, not a rule.
- **The technique has no outside citation, and the module says so.** Trimming the
  run-out is standard practice and is cited where it is acted on. Locating it by
  correlating against the revolution period is this repository's own construction,
  inherited from `periodicity`, which was itself built in-house for a dub side
  where level had already failed. The field's tools — Audacity, VinylStudio, Wave
  Corrector — detect track breaks from level and expect a person to adjust them.
  The phenomenon behind it, a groove defect struck once per turn, is common
  knowledge; reading it as a boundary detector is not.
- **`silence` is unchanged, and its trailing `music_end_sample` is still wrong.**
  Three attempts to fix it in place are recorded above; each traded one failure
  for another, and one of them moved an interior boundary. The field is left as it
  is, with the defect documented in the model and in `docs/architecture.md`, and
  callers are routed to `run_out` instead. Nothing downstream of `silence` moves,
  which is the point: `boundaries`, `clicks` and `periodicity` all read its
  regions.
- **The head of a side is not fixed.** `lead_in_end_sample` has the mirror flaw and
  no mirror measurement exists, so the first track's start still needs
  `band_profile` read by hand — which on the originating record was necessary on
  all four sides, every one of them opening with a band-limited element, and one
  entrance sitting 1.2 s before `music_start_sample` fired. Building the mirror is
  the obvious next record, and it would rest on the same single album.
- **The anchor's resolution is structural.** `periodicity` windows are 12 s on a
  4 s hop, so without the band refinement the answer is only that coarse. Where
  `band_profile` is absent the section reports nothing rather than the anchor
  alone, and `meta.confidence` is how far the refinement had to move — a wide
  bracket is a warning, not a detail.
- A recording that **ends in music** reports `null`, detected without a threshold:
  the last `periodicity` window still looks like programme. Level cannot catch
  that case at all, because with no run-out in the file the trailing reference is
  the music's own level, which the music then trivially satisfies.

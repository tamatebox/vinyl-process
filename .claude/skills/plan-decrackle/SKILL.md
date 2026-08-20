---
name: plan-decrackle
description: Choose the crackle repair threshold, event width and strength from click statistics and the repair-rate band. Produces the decrackle section of processing_plan.json. Use when a listener reports continuous crackle or surface texture rather than discrete clicks.
---

# Plan Decrackle

Repair the crackle bed: one-to-three sample events, repeated densely enough to be
heard as a texture rather than as countable ticks. Runs on the whole side, after
`declick`, before the cuts.

**This is not `declick` with a lower threshold, and reaching for that is how a day
gets spent.** The two answer different questions and the reason is in *Outside
references*. If a listener reports discrete ticks, you are in the wrong skill.

Disabled by default. The threshold has **no default**, and the reason is the same
as `declick`'s: no setting suits two pressings.

## Outside references

Where a number below is a matter of restoration practice rather than of this
codebase, it is cited. Anything here without a citation is an in-house judgement
and should be treated as uncalibrated until someone finds a source for it.

**What crackle is, and why it needs its own algorithm.** The
[ClickRepair 3.9 manual](https://archive.org/stream/manualzilla-id-5804727/5804727_djvu.txt)
(Brian Davies) separates DeClick from DeCrackle, and says why:

> "The detection/repair algorithms used for click removal are not particularly
> attuned to the removal of **very short (1–3 sample), rapidly repeated, small
> clicks**, which are usually heard as 'crackle' or 'buzz' (not 'hiss')."

DeCrackle is "a post process which **examines every sample individually** and
adjusts those which are sufficiently out of line", against click removal's "more
**collective** decision making process, making it likely that small clicks could be
overlooked when they are closely spaced". So the 1–3 sample figure is cited — it is
why `max_event_width_samples` defaults to 3 and why `lint` warns above it — and so
is the per-sample nature of the detector. The manual also notes crackle is
"particularly prevalent with **shellac (78) recordings**", which is the material
where this stage earns most.

**How much repair is normal — the same band, and it is the stopping condition.**
The manual's repair-rate benchmark is stated for the record, not for one control:

> "For a vinyl record, repairing more than **1 in 200 samples** should be viewed
> with suspicion, although it might lead to results that are more acceptable."
> "Unless your records are in really good condition, it is unlikely that the
> repair rate will fall below about **1 in 1000–2000 samples**."

So `declick` and `decrackle` together are held against 1 in 200 to 1 in 2000, and
the executor now puts the figure in the receipt: each repair stage's `detail`
carries `repaired N of M samples (1 in K)`. Read it there rather than diffing
renders.

**The stopping condition, and its honest status.** Past the band, the answer is
that the pressing is beyond the tool. The **band** is cited; the *instruction to
stop* is **not** — the manual states no such rule, and "1 in 200 should be viewed
with suspicion" is hedged in the source itself with "although it might lead to
results that are more acceptable". Treat it as this project's judgement: past 1 in
200, say out loud that you are outside the practitioner band and that further
repair trades music for texture. Do not present that as someone else's rule, and
do not keep lowering the threshold in search of a setting that exists.

**Over-repair has a named sound.** "Aggressive de-crackling can **take the edge
off voice, cymbals, etc.**" That is the thing to listen for, and it is the same
family of damage `declick` risks. Name those two — a voice and a cymbal — at the
checkpoint, because they are where it shows first.

**Do not run pitch protection with this.** The manual is explicit: "Use of 'Pitch
Protection' together with 'DeCrackle' **may seriously impair de-crackling**", and
recommends processing sequentially instead. `declick.params.confirm_k` is this
engine's nearest equivalent to pitch protection, so a plan that sets it *and*
enables `decrackle` is the combination the manual warns about — `lint` reports
`decrackle-with-pitch-protection`. Choose one per pass.

**Do not carry ClickRepair's slider numbers across.** Its DeCrackle slider is "an
arbitrary percentage" where higher is more sensitive; its "Default 78" preset sets
it to 50. This engine's `threshold` is a **curvature ratio**, so *smaller* is more
aggressive, and 50 here would mean almost no repair. Only the repair-rate band
transfers — as with `declick`, and for the same reason.

## Inputs

**Uncalibrated numbers in this skill**: the ladder of starting thresholds in
*Choosing the threshold*, and `strength` **0.6–0.8** for cautious material. Both
in-house. The 1–3 sample width and the repair-rate band are cited; nothing else
here is.

From `analysis.json`:

- `clicks.threshold_sweep[]` — read the **top** of the ladder, which is the
  opposite of what `plan-declick` reads. A pressing whose highest rungs still find
  events has loud damage; one where even the lowest rungs find little in the gaps,
  yet a listener hears texture, is the crackle case. There is no `crackle` analyzer
  and no sweep for this stage — the measurement that governs it is the **repair
  rate in the receipt**, after the fact.
- `clicks.width_histogram` — `bin_edges` in ms. Crackle sits in the bottom bin;
  a histogram with nothing there is evidence you are looking at the wrong defect.
- `surface_noise.noise_floor_db` and `surface_noise.stability_db` — a worn
  pressing has a high floor *and* an unstable one. A high but stable floor is hiss,
  which this stage does not address.
- `spectral.hiss_db` — the same distinction from the other axis. **Crackle is not
  hiss** and the manual says so in the quote above; if the complaint is a steady
  bed with no impulsiveness, this is the wrong stage and there is no de-noise
  stage yet.

## What this detector cannot do

**Bright material masks quiet crackle, and the stage under-repairs rather than
over-repairs there.** The statistic divides a sample's curvature by the mean
curvature of its own neighbourhood, and high-frequency programme content raises
that denominator: measured here, a 3.1 kHz tone at −22 dBFS carries a curvature of
its own comparable to a crackle event 40 dB below the programme, and detections
across the same injected bed fell by more than half against the same bed under a
bass line.

Three things follow, and they are properties of the algorithm rather than of any
pressing:

- **A threshold does not transfer between passages.** The rate the receipt reports
  is an average over a whole side, so a side with a bright half and a dull half is
  being repaired unevenly at any single setting. Say so if the material is like
  that; do not lower the threshold until the bright half comes up, because the dull
  half is what pays for it.
- **The failure direction is the safe one.** Fewer detections on the material where
  interpolation would be most audible — a cymbal, a bright vocal — is the way round
  you want it. This is the same reason `strength` below 1.0 is rarely needed here.
- **A crackle bed genuinely below the material's own curvature is not reachable by
  this algorithm at all.** Not at any threshold: it is not a sensitivity problem,
  it is the statistic. That is a real stopping point, and it is where the honest
  answer is that the pressing is beyond the tool.

## Choosing the threshold

There is no sweep for this and no analyzer, so the loop is: pick, render, read the
rate off the manifest, adjust. Two or three iterations, and the rate is the metric
rather than a count.

1. Start at **5**. On synthesised material with 1-sample events injected at a
   realistic density, that lands around 1 in 350 — inside the band — while 3 lands
   near 1 in 120, outside it and on the suspicious side. Those figures are from a
   test fixture, not from a record, so treat them as *where to start the ladder*
   and nothing more.
2. Render into `review/decrackle/` and read
   `manifest.stages[].detail` for the decrackle stage: `repaired N of M samples
   (1 in K)`. Place K against 1 in 200 – 1 in 2000.
3. **Below the band** (K larger than 2000): the stage is doing less than a listener
   will notice. Lower the threshold.
4. **Above the band** (K smaller than 200): stop, and say so. See the stopping
   condition above.
5. Confirm by ear on a voice and a cymbal, which is where over-repair shows first.
6. State the rung, the measured rate, and the band in `decision.rationale`.

Do **not** iterate towards "no crackle audible". The detector's statistic is a
ratio against the local neighbourhood, so there is always a lower threshold that
finds more, and the music runs out before the crackle does.

## Output

```jsonc
"decrackle": {
  "enabled": true,
  "engine": "native",                 // only 'native' implements decrackle
  "algorithm": "curvature_ratio",     // names the detector, per adr/0010
  "threshold": 5.0,                   // curvature ratio; smaller = more aggressive
  "max_event_width_samples": 3,       // 1-3 is what crackle is; lint warns above
  "strength": 1.0,                    // 0.6-0.8 for cautious material
  "params": {},                       // context_ms (5.0), interpolator (linear|hermite)
  "decision": { "skill": "plan-decrackle", "rationale": "…", "confidence": 0.8,
                "inputs": ["analysis.json#clicks", "manifest#decrackle-repair-rate"] }
}
```

Optional in the contract at schema 3.4: a plan that omits it is valid and behaves
as disabled. Write it out with a `rationale` once considered.

`lint` findings that belong here: `decrackle-without-threshold` (an error),
`decrackle-width-is-clicks`, `decrackle-without-declick`,
`decrackle-with-pitch-protection`.

## Checkpoint

**Lead with the repair rate, not with whether it sounds better.** The rate has an
outside reference; "sounds better" does not, and a stage that removes texture
always sounds smoother on first listen.

Render it — `decrackle` on, `normalize` still off, into `review/decrackle/`, so it
differs from `review/declick/` by this stage alone:

```sh
vinyl-process execute plan-side-a.json --audio <recording> \
  -o review/decrackle --manifest manifest-side-a.json
```

Present:

- **the repair rate from the manifest**, against 1 in 200 – 1 in 2000, and which
  side of the band it is on. Both stages' rates, since the band covers the pair;
- how many samples that is in absolute terms, and per minute, so the scale is
  concrete;
- **that the listening test is for damage, not for improvement**: ask whether a
  voice has lost its edge and whether cymbals have gone dull. Those are the cited
  failure modes. "Is the crackle gone" is the question that leads to over-repair,
  because the answer is always "less of it" at a lower threshold;
- whether `declick.params.confirm_k` is set, and if so that the manual expects
  this stage to under-perform as a result;
- your recommendation, and that `"enabled": false` is a legitimate answer — on a
  pressing whose crackle is the pressing, it is the honest one.

Plot it against `review/declick/` — `python scripts/plot_review.py
review/decrackle` — but say what the figure can and cannot show. Thousands of
1-sample corrections at the noise floor are invisible in a waveform and in a dB
envelope alike. The figure's job here is negative: it confirms that nothing *large*
moved. See [plan-album](../plan-album/SKILL.md#looking-at-the-render).

## Rules

- Never run repairs yourself; the executor does.
- Runs **after `declick`, before `split`**, on the whole side. Discrete defects
  before continuous ones, and that ordering is
  [adr/0012](../../../docs/adr/0012-the-executor-has-a-pre-split-phase.md).
- `threshold` is a **curvature ratio**: smaller is more aggressive. Do not copy a
  `declick` threshold into it — that one is an energy ratio over a 40 ms window and
  the two numbers mean different things — and do not copy a ClickRepair
  sensitivity.
- Events wider than `max_event_width_samples` are **dropped, not repaired**. This
  stage cannot bridge anything `declick` would have found, which is what keeps the
  two from fighting over the same samples. Raising the width to catch clicks is
  using the wrong stage.
- `interpolator` defaults to `linear`, and that is deliberate: across one to three
  samples a straight line between the two survivors cannot leave the range they
  span, so it cannot diverge on any material. `hermite` is available; which is
  better is unsettled here for the same reason it is in `declick`.
- Re-analysing a de-crackled file still reports events. The statistic is relative,
  so with the loud ones gone it resolves the repair's own seams. Never iterate
  towards zero.

---
name: plan-declick
description: Choose the declick engine, algorithm, threshold, click width and strength from analyzer click statistics. Produces the declick section of processing_plan.json. Use when planning click/pop repair for a vinyl recording.
---

# Plan Declick

Select repair parameters from measurement. The analyzer measured, DSP will
repair; you decide *how much*. Over-repair is a real cost: every repaired sample
is interpolated audio.

## Outside references

Where a number below is a matter of restoration practice rather than of this
codebase, it is cited. Anything here without a citation is an in-house judgement
and should be treated as uncalibrated until someone finds a source for it. The
sweep tells you what a rung *finds*; only an outside figure tells you whether that
amount of repair is reasonable, and a rung picked without one can sound cautious
while doing almost nothing.

**How much repair is normal.** The practitioner benchmark is a **fraction of
samples repaired**, and the
[ClickRepair 3.9 manual](https://archive.org/stream/manualzilla-id-5804727/5804727_djvu.txt)
(Brian Davies) states it outright:

> "For a vinyl record, repairing more than **1 in 200 samples** should be viewed
> with suspicion, although it might lead to results that are more acceptable."
> "Unless your records are in really good condition, it is unlikely that the
> repair rate will fall below about **1 in 1000–2000 samples**."

So the working band is roughly **1 in 200 to 1 in 2000**, and *below* it the repair
is probably not addressing what a listener hears. This is the only figure in this
skill with an outside reference behind it, which is why the checkpoint reports it.

**Sensitivity is a trade-off with no clean answer, and the manual says so:**

> "It is impossible to distinguish music from damage, with absolute certainty."
> "It is impossible to choose a sensitivity which will see all clicks removed, no
> matter how small, with no false detections."

The endorsed strategy is **the lowest sensitivity that removes the audible
clicks** — iterate by ear, which is what the checkpoint is for — with one warning
worth quoting: "beware of reducing the sensitivity too much. **Half-removed clicks
may sound like pops.**" Material shifts the answer: heavy damage takes more
sensitivity, while "some **vocals** are particularly difficult" and percussive
material harder still, both because they false-detect.

**Do not carry ClickRepair's slider numbers across.** Its scale is sensitivity, so
larger is more aggressive; `block_ratio`'s `threshold` is a ratio of energies, so
*smaller* is more aggressive. Only the repair-rate band transfers.

**Crackle is a different algorithm, and this pipeline does not have it.** The same
manual separates its DeClick and DeCrackle controls because:

> "The detection/repair algorithms used for click removal are not particularly
> attuned to the removal of very short (1–3 sample), rapidly repeated, small
> clicks, which are usually heard as 'crackle' or 'buzz' (not 'hiss')."

Its DeCrackle is "a post process which examines **every sample individually**",
against click removal's "more **collective** decision making process".
`block_ratio` is the collective kind. So when a listener reports crackle rather
than discrete clicks, lowering `threshold` is the wrong lever — it buys false
repairs on the music long before it addresses a bed of 1–3 sample events. Say that
it is out of scope here rather than chasing it.

**Pitch protection has a local equivalent.** `params.confirm_k` is this engine's
nearest thing to ClickRepair's **Pitch Protection**, which "avoids periodic false
repairs to the hard edge of high-energy pitched sound, such as brass instruments
and some voice". That is what makes a low rung usable on vocal material, so pair
them rather than treating `confirm_k` as exotic.

**Time-reversed processing does not transfer — do not implement it.** The manual
recommends reversing the file, processing, and reversing back, because "some
percussive sounds have a sharp attack and relatively slower decay, and when played
backwards, that becomes a slow attack with a sudden end", which its detector
confuses less often. The benefit is about *false detection* and it requires a
time-asymmetric detector. `block_ratio` is symmetric by construction: both the
detect and the context window are centred means, and the high-pass ahead of them
is zero-phase. Measured on one track: the same event count forward and reversed,
all but one event identical to within two samples, and that one a single sample of
rounding. The asymmetry in this engine is all in the *repair* (AR prediction,
Hermite's one-sided tangents), which is not what the technique addresses.

**Uncalibrated numbers in this skill**, named so nobody mistakes them for
practice: `max_click_width_ms` **2.0** (and **4.0** for a populated width
histogram), `strength` **0.6–0.8** for conservative intent, the **−30 dBFS** line
this skill calls "the audible band", and the **~5 ms** span-merge at the
checkpoint. All in-house. The repair-rate band is the only calibrated figure here,
which is exactly why the checkpoint leads with it.

## Inputs

From `analysis.json`:

- `clicks.threshold_sweep[]` — **read this first, and read it instead of the
  headline count.** Each rung gives `threshold`, `count` and the two rates below.
  Choosing the rung is this skill's main decision; see *Reading the sweep*.
- `clicks.silence_rate_per_minute` versus `clicks.programme_rate_per_minute` — the
  pair that makes the sweep legible. A worn pressing crackles in the inter-track
  gaps as much as under the music; a detector over-triggering on the material
  fires only under the programme. The two readings are not subtle: a detector
  following bass-heavy material has read two orders of magnitude more under the
  programme than in the gaps, which would have meant interpolating tens of
  thousands of musical transients.
- `clicks.count`, `clicks.rate_per_minute` — the rung named by
  `meta.params.threshold_ratio`, promoted for convenience. A reporting choice, not
  a recommendation: do not treat it as the answer.
- `clicks.amplitude_histogram` — `bin_edges` in dBFS; the tail tells you whether
  the damage is loud or merely present
- `clicks.width_histogram` — `bin_edges` in ms; loud clicks tend to be wider
- `clicks.density_per_minute` — localised damage (one bad passage) versus a
  uniformly worn side
- `clicks.positions_sample` — where the detections are, `positions_truncated` when
  there were more than the analyzer records (5000 by default), so the list is a
  prefix and not the whole set.

  **The three histograms, the density and the positions all describe the promoted
  rung only** — the sweep carries counts and rates per rung, nothing else. Once you
  have chosen a different rung, they no longer describe your decision: re-analyze
  at it (see *Reading the sweep*) rather than reading them across.
- `transients.mean_per_second`, `transients.peak_per_second` — percussive
  material is where false positives get audible
- `surface_noise.noise_floor_db`, `spectral.hiss_db`

Plus `preferences.declick_intent` (`conservative` / `balanced` / `aggressive`).

## Reading the sweep

There is no threshold that suits every pressing, and none that even suits both
sides of every album; measured cases exist where side A and side B wanted
different rungs ([adr/0010](../../../docs/adr/0010-the-click-statistic-is-local.md)).
So the analyzer reports the curve and you pick the point, per recording, from what
the curve says about *that* recording.

The curve has two ends and both are wrong:

- **Too low.** The programme rate approaches or passes the silence rate. Surface
  damage is on the surface, so it must appear in the gaps too; a detector firing
  mostly under the music is following the music. Reject these rungs outright.
- **Too high.** Nothing is found even in the gaps, where there is no music to be
  confused by. Real damage is being missed.

Between them, the **silence rate is your estimate of the surface damage density**,
because a gap is unmasked. The programme rate falls below it by however much the
music masks — which is a feature, not a loss: a click you cannot hear under the
programme does not need interpolating.

**The two rates are not enough on their own.** Two more figures come with each
rung and both have overturned a choice made on the rates alone:

- `onset_coincidence` — how much more often than chance the rung's detections land
  on a rising edge. Near 1 means the detector is indifferent to note attacks;
  several times that means it is following them, and the repair would interpolate
  over the attacks. It has overturned the rates test outright: a rung can beat its
  own programme rate by more than 40 to 1 and still read close to 8, with its
  detections spaced at the beat rather than at the platter. And a **whole sweep
  reading above 2 is itself the answer** — no threshold on that pressing was safe,
  and repair stayed off.
- `revolution_lock` — Rayleigh's statistic for the detections folded onto the
  platter's period. Its null is exponential with mean 1 whatever the count, so
  rungs are comparable; 3 is suggestive and 5 strong. **A high value argues for
  repair, not against it.** A defect crossing the groove spiral is struck at the
  same phase of every turn, and that tick is the most audible damage a record can
  have. Reading "periodic" as "musical" would throw away exactly the clicks a
  listener notices most.

So: reject rungs where the rates are at parity, reject rungs whose
`onset_coincidence` sits well above 1 unless `revolution_lock` explains them, and
among what survives pick the lowest.

Then **verify it by ear before trusting it**, and verify *that rung*. Only the
promoted rung's detections are recorded, so unless you chose it, re-analyze with
the ladder's promotion moved to your rung — a config file, not a script, and its
effect is recorded in `meta.params` and `config_digest`:

```sh
printf '[analyzer.clicks]\nthreshold_ratio = 75.0\n' > clicks-75.toml
vinyl-process --config clicks-75.toml analyze <recording> -o analysis-clicks-75.json
```

Now `positions_sample` is your rung's. Take a handful of the detections that fall
inside a `silence.regions[]` gap, cut two seconds around each, amplify so the
surface is audible at all, and listen for the click at the position claimed. A gap
holds no programme material, so anything impulsive there is damage by definition —
this is the only positive evidence available. On a well-chosen rung a spot check
of a dozen gap detections has come back entirely real, which is the outcome to
expect; anything less is a reason to move up the ladder. Amplitudes are not
recorded per detection (only as a histogram), so pick by position, not by loudness.

Then say how much of it reaches the album. Detections in the dead middle of a gap,
the lead-in and the run-out are dropped by the split and cost nothing to ignore;
only the ones inside the exported cuts matter. Expect to lose a third to a half of
them that way, and expect the survivors to be uneven: on one side more than half
the in-cut detections fell in the fade-in and fade-out of a single quiet track.
The surface is uniform; its visibility is not.

**No gaps, no calibration.** A continuous side, a live recording or a gapless
album gives the sweep nothing unmasked to measure: with no silent stretch of at
least `silence_min_seconds` (2 s), `silence_rate_per_minute` comes back `null` on
every rung, and so does `programme_rate_per_minute` when there is nothing to
compare it against. Check for `null` before comparing, say so, and either borrow a
threshold from another side of the same pressing or leave repair off; do not pick a
rung from the count alone.

**No `clicks` section at all** — the analyzer failed or was not selected, which
`analyzers[]` reports — is not a reason to guess either. Re-run
`analyze --analyzers silence,clicks`; if it will not run, set
`"enabled": false` and say why.

## How much repair is normal

The band is in *Outside references*: roughly **1 in 200 to 1 in 2000** samples
repaired. What belongs here is how to measure your rung against it, and how not to.

**Compute the rate from the render, not from the plan.** The interpolated sample
count is the total width of the spans where `review/declick/` differs from
`review/split/`, over the total samples exported. `count` cannot stand in for it:
a count is events, the band is samples, and most of a recording's events never
reach the album.

The failure mode this guards against has been measured twice on one record: a rung
chosen by feel came out at **1 in 27 000** — more than an order of magnitude below
the band's floor — and the verdict on it was "somewhat better", which is exactly
what that number predicts. A rung two steps lower measured inside the band, and
had been dismissed as over-repair against nothing at all. Neither choice was
wrong by argument; both were made without the figure.

Report the rate at the checkpoint. Below the band, say so and say what it implies:
the repair is doing less than the listener will notice.

**Do not measure the residual over a window wide enough to contain music.** Every
attempt to quantify "is the click gone" over ±30 ms, or against a median taken
over ±300 ms, reports the track's own high-frequency content instead: such a
metric has read tens of dB of "residual" where the sample values showed a clean
repair, and a whole sweep built on it was void. Judge at the detector's own scale
— a few hundred microseconds against its immediate neighbourhood — keep a control
set of positions where nothing was detected, and **when a figure and the sample
values disagree, believe the samples.**

## Decision guide

1. **Algorithm** — `native` / `block_ratio`, the only one the native engine has.
   Its detector is the one the sweep was measured with, and its answer does not
   change with how much audio it is handed, so the analyzer's statistics describe
   what the engine will actually repair. That property is the whole reason the
   detector was replaced, and why `threshold` has no default: see
   [adr/0010](../../../docs/adr/0010-the-click-statistic-is-local.md). `ffmpeg`
   (`adeclick`) remains an option for heavily damaged sides; check availability
   with `vinyl-process engines`.
2. **Skip entirely** (`"enabled": false`) when no rung of the sweep has a silence
   rate that dominates its programme rate, or when the rungs that do are empty:
   there is either nothing to repair or nothing you can distinguish from the
   music. Skip it too when the amplitude histogram is empty above −30 dBFS and the
   surviving count is small — the repair risk exceeds the benefit.
3. **Threshold** — for `block_ratio` this is a **ratio of energies, not a sigma
   count**, and it comes from the sweep (see *Reading the sweep*), not from a
   default. Do not carry a value across pressings, across algorithms, or even
   between the two sides of one record. State in the rationale which rung you
   chose, what its two rates were, and that you verified its gap detections by
   ear.
4. **max_click_width_ms** — 2.0 default. Go up to 4.0 only when the width
   histogram is populated above 1 ms. On `native` this value is also the rejection
   rule — anything wider is treated as programme material, not damage — and it is
   what the AR order and window are derived from. On `ffmpeg` it is neither: it maps
   to `adeclick`'s analysis *window*, clamped to 10–100 ms and never narrower than
   four click widths, so nothing is rejected for being wide. Do not read a width
   across engines any more than a threshold.
5. **Strength** — 1.0 for obvious damage; 0.6–0.8 for `conservative` intent or
   sparse damage on precious material.
6. **params** — the escape hatch for engine-specific knobs, recorded in the plan
   so the run stays reproducible. `block_ratio` accepts `interpolator`
   (`ar` | `hermite` | `linear`, default `ar`), `detect_ms` (0.2), `context_ms`
   (40.0), `highpass_hz` (3000), and `ar_order` / `ar_iterations` / `ar_context`.
   Leave the last three alone: the order and window are *derived* from
   `max_click_width_ms` by the published rule for this interpolator, and the numbers
   that used to be hard-coded there were an order of magnitude off it. **Which
   interpolator is best is not settled** — comparisons by SNR against self-injected
   damage were discarded as circular, and there is no public benchmark with clean
   references to appeal to. If it matters for a record, render two and listen.
   `confirm_k` is available and off by default: it discards candidates that a few
   sinusoids already explain, which lets a low rung stay sensitive to quiet clicks
   without following the music. Switching it on is a decision — record it and its
   `confirm_components` / `confirm_margin` in the rationale. `ffmpeg` accepts
   `window_ms`, `overlap`, `ar_order`, `burst_fusion`, `method`.
7. **preset** — leave it `null`. The field is in the contract but no engine
   interprets it; a value here would read as a decision that nothing acts on.

## Output

```jsonc
"declick": {
  "enabled": true,
  "engine": "native",
  "algorithm": "block_ratio",       // 'adeclick' for the ffmpeg engine
  "threshold": 50.0,               // a rung of clicks.threshold_sweep; no default
  "max_click_width_ms": 2.0,
  "strength": 1.0,
  "preset": null,                  // no engine reads this yet
  "params": {},                    // e.g. {"interpolator": "hermite"}
  "decision": { "skill": "plan-declick", "rationale": "…", "confidence": 0.85,
                "inputs": ["analysis.json#clicks", "analysis.json#transients"] }
}
```

## Checkpoint

Repair is destructive in the sense that matters: every repaired span is
interpolated audio. Present, before deciding:

- `clicks.silence_rate_per_minute` against `clicks.programme_rate_per_minute` —
  and say which of the two readings this is (worn pressing, or detector
  over-triggering on the material). Present the silence rate as what it is: a
  **detector diagnostic**, not a measure of the album's damage. It pools every
  detected silence, and most of those are the lead-in and the run-out, which the
  split discards whole. The two figures have differed by a **factor of over 100**
  on one measured side — a pooled rate dominated by the lead-in, against well under
  1/min inside the exported tracks. Quote the pooled figure to argue the detector
  is finding damage rather than music; never quote it as how worn the album is;
- the amplitude histogram in one line: how many events are above −30 dBFS, which
  is the audible band, against how many sit near the noise floor;
- which rung you chose, and **how many of its detections fall inside the exported
  cuts** — that, not `count`, is how many spans the repair would interpolate.
  Declick runs after the split, per track, so a detection in the lead-in, the
  run-out or the dead middle of a gap is never repaired and never heard. `count` is
  the whole recording and overstates the work by however worn the unplayed parts
  are — **by half to three quarters** on the two sides where it has been counted.
  Give the in-cut figure in total and per minute, break it down per track so a
  concentration shows, and if you had to re-analyze to get the positions, say the
  figures come from that run;
- **the repair rate, as a fraction of samples**, measured off the render and
  placed against the 1-in-200-to-1-in-2000 band from *How much repair is normal*.
  A rung below that band is doing less than the listener will notice, and saying so
  is more useful than any count;
- your recommendation and what it costs if it is wrong.

`"enabled": false` is a legitimate answer and is often the right one.

Then **render it and let them hear both**. Numbers decide whether a repair is
plausible; only listening decides whether it helped. Execute the plan with
`declick` on and `normalize` still off, into `review/declick/`, and compare
against `review/split/` from the previous checkpoint — the two differ by the
repair alone:

```sh
vinyl-process execute plan-side-a.json --audio <recording> \
  -o review/declick --manifest manifest-side-a.json
```

Keep `normalize` off for this. A repaired render that is also louder will be
preferred whatever the repair did, and the level has not been agreed yet.

Plot it — `python scripts/plot_review.py review/declick` — and compare each track
against the same track in `review/split/plots/`. The two renders differ by the
repair alone, so anything visible between them *is* the repair. A dB panel that
has lost its tallest peak spikes is the interpolation showing up; use it to check
that what disappeared is what you meant to remove, on the tracks with the highest
in-cut density. It will not show you a dulled attack — that is audible long before
it is visible, which is why this checkpoint is a listening one. See
[plan-album](../plan-album/SKILL.md#looking-at-the-render).

Repair is easiest to hear where the detector fired hardest, so name the two or
three tracks with the highest `density_per_minute` and suggest starting there. Ask
whether the clicks are gone and, more importantly, whether anything else changed —
dulled transients, a smeared cymbal, a lost attack. Interpolated audio is what
over-aggressive repair leaves behind, and it is audible long before the numbers
look wrong.

**Name the repairs in `mm:ss.ss` within the exported track, or the listening does
not happen.** A track and a rate is not a place: "3:00 of 爪, 20.97/min" leaves
someone scrubbing for a defect that lasts under half a millisecond. Take the
positions from the sample-wise difference between the two renders, not from
`clicks.positions_sample` — the diff is what the engine actually repaired on the
split buffer, the positions are the analyzer's guess on the whole file, and they
disagree by a few events. Merge spans closer than ~5 ms (one click can produce two
adjacent ones), then give:

- **the loudest three or four corrections**, as position, correction in dB and the
  click's own peak — these are the ones a person can hear singly. One line each,
  e.g. `1:40.41  −14.1 dB (click peak −9.3 dBFS)`;
- **for a periodic defect, the runs where it is densest**, as a time range rather
  than a list, plus the phase. A strong `revolution_lock` shows up as a handful of
  ticks spaced at exactly the platter period and all sitting within a few tens of
  milliseconds of the same phase of it — one such diagnosis, sixty-odd events, was
  settled in fifteen seconds of listening once two stretches were named. The phase
  is the evidence in one line; a list of sixty positions is not;
- **the album's peak, if the repair moved it.** A click is often the loudest
  sample on a side, so removing one lowers the album peak — measured once at
  **1.1 dB** from a single tick. Say so here, because that is gain
  `plan-normalize` will find at the next checkpoint, and the two decisions
  otherwise look unrelated;
- **where the corrections are all small, say the difference may be inaudible and
  what follows from that.** A side whose largest correction is in the −20s of dB
  warrants the honest framing: if you hear nothing, either answer is fine; if you
  hear a dulled attack, this side alone goes off. `enabled` is per plan, so per
  side.

The A/B copies must share one gain. `review/split-loud/` already carries a flat
gain from the previous checkpoint; apply **that same figure** to a
`review/declick-loud/`, computed from the *split* render's peak and deliberately
not recomputed. Recomputing makes the repaired copy louder by however much the
repair took off the peak — a dB or so is enough — and a louder copy wins an A/B
whatever the repair did. Say in the README of both that they differ by the repair
alone.

## Rules

- Never run repairs yourself; the executor does.
- Declick runs *after* split, per track, *before* normalization. Assume that
  ordering when reasoning about levels.
- Re-analysing a declicked file still reports clicks: with the loud ones gone the
  detector's relative threshold drops and it resolves the repair's own seams,
  around −60 dBFS. Judge the result by the *amplitude* histogram, not the count,
  and never iterate towards `count == 0`.
- The `ffmpeg` engine cannot honour `strength` below 1.0 and will refuse the
  plan rather than silently ignore your decision. Its `threshold` is adeclick's
  own 1–100 scale, not sigmas — do not copy a native threshold across engines.

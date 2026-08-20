---
name: plan-declick
description: Choose the declick engine, algorithm, threshold, click width and strength from analyzer click statistics. Produces the declick section of processing_plan.json. Use when planning click/pop repair for a vinyl recording.
---

# Plan Declick

Select repair parameters from measurement. The analyzer measured, DSP will
repair; you decide *how much*. Over-repair is a real cost: every repaired sample
is interpolated audio.

## Inputs

From `analysis.json`:

- `clicks.threshold_sweep[]` — **read this first, and read it instead of the
  headline count.** Each rung gives `threshold`, `count` and the two rates below.
  Choosing the rung is this skill's main decision; see *Reading the sweep*.
- `clicks.silence_rate_per_minute` versus `clicks.programme_rate_per_minute` — the
  pair that makes the sweep legible. A worn pressing crackles in the inter-track
  gaps as much as under the music; a detector over-triggering on the material
  fires only under the programme. On one bass-heavy pressing the split was 9/min
  against 1100/min, and declicking would have interpolated 17 000 musical
  transients.
- `clicks.count`, `clicks.rate_per_minute` — the rung named by
  `meta.params.threshold_ratio`, promoted for convenience. A reporting choice, not
  a recommendation: do not treat it as the answer.
- `clicks.amplitude_histogram` — `bin_edges` in dBFS; the tail tells you whether
  the damage is loud or merely present
- `clicks.width_histogram` — `bin_edges` in ms; loud clicks tend to be wider
- `clicks.density_per_minute` — localised damage (one bad passage) versus a
  uniformly worn side
- `transients.mean_per_second`, `transients.peak_per_second` — percussive
  material is where false positives get audible
- `surface_noise.noise_floor_db`, `spectral.hiss_db`

Plus `preferences.declick_intent` (`conservative` / `balanced` / `aggressive`).

## Reading the sweep

There is no threshold that suits every pressing, and none that even suits both
sides of every album — on the one this procedure was written against, side A and
side B wanted different rungs. So the analyzer reports the curve and you pick the
point, per recording, from what the curve says about *that* recording.

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

Pick the lowest rung whose silence rate clearly dominates the programme rate, then
**verify it by ear before trusting it**. Cut two seconds around the loudest few of
its gap detections, amplify so the surface is audible at all, and listen for the
click at the position it claims. This is the only positive evidence available: a
gap holds no programme material, so anything impulsive there is damage by
definition. On the record this was written against, twelve of twelve were real.

Then say how much of it reaches the album. Detections in the dead middle of a gap,
the lead-in and the run-out are dropped by the split and cost nothing to ignore;
only the ones inside the exported cuts matter. On that record it was 163 of 259,
and 86 of those sat in the fade-in and fade-out of a single quiet track — the
surface was uniform, the visibility was not.

**No gaps, no calibration.** A continuous side, a live recording or a gapless
album gives the sweep nothing unmasked to measure, and both rates collapse into
one number. Say so, and either borrow a threshold from another side of the same
pressing or leave repair off; do not pick a rung from the count alone.

## Decision guide

1. **Algorithm** — `native` / `block_ratio`, the only one the native engine has.
   Its detector is the one the sweep was measured with, and its answer does not
   change with how much audio it is handed, so the analyzer's statistics describe
   what the engine will actually repair. A robust-sigma detector used to sit
   beside it and was removed: its threshold was one sigma over the whole input,
   which drifted by up to 7.8x across chunk sizes on real audio and fired 348 to
   1611 times more under the programme than in the inter-track gaps. `ffmpeg`
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
   histogram is populated above 1 ms. This value is also the rejection rule:
   anything wider is treated as programme material, not damage.
5. **Strength** — 1.0 for obvious damage; 0.6–0.8 for `conservative` intent or
   sparse damage on precious material.
6. **params** — the escape hatch for engine-specific knobs, recorded in the plan
   so the run stays reproducible. `block_ratio` accepts `interpolator`
   (`ar` | `hermite` | `linear`, default `ar`), `detect_ms`, `context_ms` and
   `highpass_hz`; the AR order and window are derived from `max_click_width_ms` by
   the published rule and should be left alone. **Which interpolator is best is
   not settled** — comparisons by SNR against self-injected damage were discarded
   as circular, and there is no public benchmark with clean references to appeal
   to. If it matters for a record, render two and listen. `ffmpeg` accepts
   `window_ms`, `overlap`, `ar_order`, `burst_fusion`, `method`.

## Output

```jsonc
"declick": {
  "enabled": true,
  "engine": "native",
  "algorithm": "block_ratio",       // 'adeclick' for the ffmpeg engine
  "threshold": 50.0,               // a rung of clicks.threshold_sweep; no default
  "max_click_width_ms": 2.0,
  "strength": 1.0,
  "preset": null,
  "params": {},
  "decision": { "skill": "plan-declick", "rationale": "…", "confidence": 0.85,
                "inputs": ["analysis.json#clicks", "analysis.json#transients"] }
}
```

## Checkpoint

Repair is destructive in the sense that matters: every repaired span is
interpolated audio. Present, before deciding:

- `clicks.silence_rate_per_minute` against `clicks.programme_rate_per_minute` —
  and say which of the two readings this is (worn pressing, or detector
  over-triggering on the material);
- the amplitude histogram in one line: how many events are above −30 dBFS, which
  is the audible band, against how many sit near the noise floor;
- how many spans the proposed threshold would interpolate, in total and per
  minute;
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

Repair is easiest to hear where the detector fired hardest, so name the two or
three tracks with the highest `density_per_minute` and suggest starting there. Ask
whether the clicks are gone and, more importantly, whether anything else changed —
dulled transients, a smeared cymbal, a lost attack. Interpolated audio is what
over-aggressive repair leaves behind, and it is audible long before the numbers
look wrong.

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

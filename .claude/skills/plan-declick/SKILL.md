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

- `clicks.silence_rate_per_minute` versus `clicks.programme_rate_per_minute` —
  **read these first.** A worn pressing crackles in the inter-track gaps as much
  as under the music; a detector over-triggering on the material fires only under
  the programme. On one bass-heavy pressing the split was 9/min against 1100/min,
  and declicking would have interpolated 17 000 musical transients.
- `clicks.count`, `clicks.rate_per_minute`
- `clicks.amplitude_histogram` — `bin_edges` in dBFS; the tail tells you whether
  the damage is loud or merely present
- `clicks.width_histogram` — `bin_edges` in ms; loud clicks tend to be wider
- `clicks.density_per_minute` — localised damage (one bad passage) versus a
  uniformly worn side
- `transients.mean_per_second`, `transients.peak_per_second` — percussive
  material is where false positives get audible
- `surface_noise.noise_floor_db`, `spectral.hiss_db`

Plus `preferences.declick_intent` (`conservative` / `balanced` / `aggressive`).

## Decision guide

1. **Engine** — `native` (`mad_interpolate`) is the default and the
   reproducibility baseline: it detects robust-statistics outliers and bridges
   each click with cubic Hermite interpolation. Choose `ffmpeg` (`adeclick`) for
   heavily damaged sides (rate > 100/min) where its overlap-add repair is gentler
   at scale. Check availability with `vinyl-process engines`.
2. **Skip entirely** (`"enabled": false`) when `rate_per_minute < 2` and the
   amplitude histogram is empty above −30 dBFS: the repair risk exceeds the
   benefit. Skip it too when the programme rate dwarfs the silence rate — that is
   the detector firing on the music, and no threshold in the plan will fix a
   threshold that is global by construction.
3. **Threshold** — engine-specific scale. For `native` it is robust-sigma (MAD)
   multiples: 6.0 default; 4.5–5.0 for noisy pressings (rate > 50/min with a hot
   histogram tail); 7.0–8.0 for quiet pressings, or when
   `transients.mean_per_second` is high (brushed drums, harpsichord) and softened
   attacks would be worse than the clicks.
4. **max_click_width_ms** — 2.0 default. Go up to 4.0 only when the width
   histogram is populated above 1 ms. This value is also the rejection rule:
   anything wider is treated as programme material, not damage.
5. **Strength** — 1.0 for obvious damage; 0.6–0.8 for `conservative` intent or
   sparse damage on precious material.
6. **params** — the escape hatch for engine-specific knobs, recorded in the plan
   so the run stays reproducible. `native` accepts `highpass_hz` (default 3000);
   `ffmpeg` accepts `window_ms`, `overlap`, `ar_order`, `burst_fusion`, `method`.

## Output

```jsonc
"declick": {
  "enabled": true,
  "engine": "native",
  "algorithm": "mad_interpolate",   // 'adeclick' for the ffmpeg engine
  "threshold": 6.0,
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

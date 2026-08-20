---
name: plan-normalize
description: Choose the normalization strategy (album-wide mode and target level) from analyzer peak and dynamic-range data. Produces the normalize section of processing_plan.json. Use when planning loudness or level adjustment for a vinyl recording.
---

# Plan Normalize

Choose strategy and target. The executor computes the exact gain
deterministically, post-declick and album-wide.

## Inputs

From `analysis.json`: `peaks` (`peak_db`, `rms_db`, `crest_factor_db`),
`dynamic_range` (`dr_estimate_db`, `loud_rms_db`, `percentiles`), `clipping`
(`clipped_region_count`, `longest_run_samples`). Plus
`preferences.normalize_mode` and `preferences.normalize_target_db`.

## Decision guide

1. **Default**: `mode: "album_peak"`, `target_db: -1.0`. One gain for the whole
   side preserves the relative dynamics between its tracks — that is the entire
   point of album-wide normalization.
2. `album_rms` when the user wants loudness matching across a collection. Take
   `target_db` from their stated reference (e.g. −18 dB RMS), not from a guess.
3. `track_peak` is discouraged: it flattens the level relationships the record
   was mastered with. Use it only for compilations assembled from genuinely
   mismatched sources, and say so in `decision.rationale`.
4. **Skip** (`"enabled": false`, or `mode: "none"`) when `peak_db` is already
   within 0.5 dB of the target, or when `clipping.clipped_region_count > 0` —
   normalizing a clipped capture amplifies the damage. Tell the user instead.

## Output

```jsonc
"normalize": {
  "enabled": true,
  "engine": "native",          // 'ffmpeg' also implements gain, bit-comparably
  "mode": "album_peak",        // album_peak | album_rms | track_peak | none
  "target_db": -1.0,
  "decision": { "skill": "plan-normalize", "rationale": "…", "confidence": 0.95,
                "inputs": ["analysis.json#peaks", "analysis.json#clipping"] }
}
```

## Checkpoint

**Ask whether the level should be touched at all.** It is a yes/no question, it
belongs to the person who owns the record, and it is the change they will notice
afterwards. Never carry the default through silently.

Present:

- `peaks.peak_db` and the target you propose;
- the gain as a *lower bound*: `target - peak_db`. The real value is usually
  larger, because the side's loudest sample is often the stylus drop in the
  lead-in, which the split excludes — on one tested pressing the bound was
  +2.4 dB and the executor applied +8.0 dB;
- for a two-sided album, both sides' `peak_db`, since each plan is normalized on
  its own and the sides can end up at different gains;
- that the exact value appears in `manifest.applied_gain_db` after the run, and
  that keeping the capture's level is `"enabled": false`.

## Rules

- Never precompute the gain value. Declick changes peaks slightly, so the
  executor measures after repair; your decision is the *strategy and target*,
  and the manifest records the gain that was actually applied.
- `target_db` must be ≤ 0 dBFS. Keep at least 1 dB of headroom for lossy
  transcodes the user may make later.
- If the source peaks above the target, the gain is negative — that is normal and
  is not a reason to skip the stage.

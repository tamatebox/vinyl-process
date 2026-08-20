---
name: plan-split
description: Decide final track boundaries for a vinyl recording by combining analyzer boundary candidates with Discogs/MusicBrainz track counts and durations. Produces the split section of processing_plan.json. Use when planning how to split a recording into tracks.
---

# Plan Split

Choose the final track boundaries. Treat this as an optimisation problem — pick
the boundary set that best explains *all* the evidence — not as "cut at every
silence".

## Inputs

From `analysis.json`:

- `boundaries.candidates[]` — `{sample, method, confidence}` with methods
  `silence`, `rms_valley`, `spectral_change`
- `boundaries.lead_in_end_sample`, `boundaries.lead_out_start_sample` — the
  playable region; the trailing silence is the run-out groove
- `silence.regions[]` — `{start_sample, end_sample, mean_rms_db, duration_seconds, confidence}`
- `rms_profile` — the envelope, when you need to look at a specific stretch
- `source.sample_rate`, `source.num_samples`

Plus the release tracklist: expected track count and per-track durations. If you
have none, ask the user for the track count before guessing.

## Procedure

1. Convert the tracklist durations into expected boundary positions (cumulative
   sums), scaled into the playable region between lead-in end and lead-out start.
2. Score candidates: high-confidence `silence` first; `rms_valley` where silence
   is missing (segued or live sides); `spectral_change` only to break ties
   between nearby candidates.
3. Match candidates to expected positions. Within ±5 % of the side's length is a
   strong match. Where no candidate is near an expected boundary, interpolate
   from the durations and say so in the `decision.rationale`.
4. Resolve count mismatches explicitly:
   - **more candidates than tracks** — drop the weakest. Quiet passages inside a
     track are the usual false positive; classical and live sides are prone to
     it, so weight the tracklist durations more heavily there.
   - **fewer candidates than tracks** — segued tracks. Place the boundary at the
     duration-derived position, snapped to the nearest `rms_valley`.
5. Emit the section.

## Output

```jsonc
"split": {
  "enabled": true,
  "engine": "native",              // only 'native' can split (sample-exact)
  "decision": { "skill": "plan-split", "rationale": "…", "confidence": 0.92,
                "inputs": ["analysis.json#boundaries", "discogs:release/1873013"] },
  "tracks": [
    { "index": 1, "start_sample": 132300, "end_sample": 11466000,
      "fade_in_ms": 20.0, "fade_out_ms": 30.0 }
  ]
}
```

## Rules

- Positions are integer samples into the *source* file. Never seconds.
- `index` starts at 1 and is contiguous; tracks must not overlap; gaps between
  tracks are normal and stay in neither track.
- The first track starts at `lead_in_end_sample` (or 0); the last ends at
  `lead_out_start_sample` (or the final sample). Cut *inside* a silence.
- Titles do not belong here — they live in the `metadata` section. The plan must
  not carry the same string twice.
- Give every track a few milliseconds of fade (10–30 ms is plenty): a vinyl cut
  lands in surface noise, and a hard edge is an audible click.

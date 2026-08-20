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
- `silence.regions[]` — `{start_sample, music_end_sample, end_sample, mean_rms_db,
  duration_seconds, confidence}`. **`music_end_sample`, not `start_sample`, is
  where the preceding track stopped**: `start_sample` is a fixed-threshold
  crossing, which on a fading track fires mid-fade (4 s early on one track of a
  tested pressing, 22 s on another).
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
5. **Place each cut from `music_end_sample`, never from `start_sample`.** A
   reasonable shape for a side of separate tracks:
   - `end_sample` = the gap's `music_end_sample` + a tail of 0.3–0.5 s;
   - `start_sample` = the gap's `end_sample` − a pre-roll of 0.3–0.5 s;
   - the dead middle of the gap is simply not exported (the contract allows a gap
     between tracks), and the tail is clamped so it never reaches the next
     track's pre-roll.

   Err long. Extra surface noise is faded out and inaudible; a clipped fade is not
   recoverable. The **last track of a side** has no following gap to decay into —
   only the run-out, which sits at the same level as the fade — so
   `music_end_sample` is a lower bound there. Interpolate that end from the
   label's duration instead, and say so in the rationale.
6. Emit the section.

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
- `index` is the track's position on the **album**, not within this plan: side B
  continues where side A stopped (6, 7, …) so both sides export into one directory
  with correct filenames and tags. Indices must be contiguous and ascending;
  tracks must not overlap; the dead middle of a gap stays in neither track.
- The first track starts at `lead_in_end_sample` (or 0); the last ends at
  `lead_out_start_sample` (or the final sample). Cut *inside* a silence.
- Titles do not belong here — they live in the `metadata` section. The plan must
  not carry the same string twice.
- Both edges need a fade, and a short one is what is needed. A vinyl cut lands in
  surface noise rather than silence, so a hard edge is a step discontinuity and
  therefore an audible click; anything under 100 ms removes it, and **20 ms in
  with 50–80 ms out** is enough. Do not go longer: a fade of a second or more
  shapes seconds of the record's own noise, which is a change to the source rather
  than a repair, and it buys nothing — the click was already gone at 80 ms. Keep
  the fade shorter than the tail, so it starts after the music has stopped and
  nothing musical is shaped by it.
- **A side that plays continuously is the opposite case.** Make the boundaries
  contiguous (`end_sample` == the next `start_sample`), set every fade to 0, and
  drop nothing: the tracks must concatenate back into the recording sample for
  sample, or every transition gets a dip. `vinyl-process lint` fails a plan that
  mixes the two (`gapless-fade`).

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
3. Match candidates to expected positions by **walking the side in order, not by
   nearest neighbour**. Take the first strong candidate lying at least a plausible
   track's worth of music past the previous cut, and let a candidate's confidence
   and the length of its gap outrank its distance from the expected position.
   Nearest neighbour fails late in a side: the expected positions drift by the
   length of every gap not yet accounted for, always towards the run-out, and ±5 %
   of a 20-minute side is ±60 s — wide enough to bracket several unrelated gaps. On
   a tested pressing the last expected boundary had four candidates at confidence
   1.00 inside the tolerance, and the nearest of them was 28 s into the run-out
   groove. Where no candidate is near an expected boundary, interpolate from the
   durations and say so in the `decision.rationale`.
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
   recoverable. The **last track of a side** has no following track to constrain
   it, but it is not unmeasured: close it at the `music_end_sample` of the first
   silence region that opens after it began, exactly like every other track — the
   walk in step 3 lands on that same region, and a nearer candidate deeper in the
   run-out is not a competitor for it. Do **not** interpolate that end from the
   label's duration — the instruction here used to say so, and it appended 11 s of
   run-out groove noise to a side whose printed duration was that much too long.
   Confirm the cut against `rms_profile` past it: a flat plateau is the run-out
   groove and the cut stands, while a level still descending means the fade is
   still running, so extend to where it flattens. The label is a cross-check —
   report a disagreement over ~5 s as a fact about the pressing, not as a reason
   to move the cut.
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

## Checkpoint

Hand back a table, one row per track: position, title, the duration you cut, the
label's duration, and the difference. Then:

- name the evidence each boundary came from (`silence`, `rms_valley`, or
  interpolated from durations because nothing was detected there);
- explain every difference over ~5 s — the usual causes are a fade the threshold
  cut short and a label duration that does not match the pressing;
- flag any boundary whose `music_end_sample` had to be overridden.

Boundaries are the one decision that cannot be checked afterwards without
listening to the whole side, so do not move on until the table is agreed.

## Rules

- Positions are integer samples into the *source* file. Never seconds.
- `index` is the track's position on the **album**, not within this plan: side B
  continues where side A stopped (6, 7, …) so both sides export into one directory
  with correct filenames and tags. Indices must be contiguous and ascending;
  tracks must not overlap; the dead middle of a gap stays in neither track.
- Start the first track from the first silence region's `end_sample`, less the
  same pre-roll every other track gets — **not** from `lead_in_end_sample`. That
  marker is where the lead-in groove stops, and the needle drop lands *after* it:
  on both sides of a tested pressing the loudest sample of the whole side was the
  drop itself, at −3.4 dBFS between `lead_in_end_sample` and the first gap, against
  −9 dBFS for the loudest music. Starting at the marker puts that pop inside track
  1 and then hands it to `album_peak`, which costs 5.6 dB of gain across the whole
  album. Likewise the last track ends at its own `music_end_sample` (step 5), not
  at `lead_out_start_sample`. Cut *inside* a silence.
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

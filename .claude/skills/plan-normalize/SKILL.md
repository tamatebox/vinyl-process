---
name: plan-normalize
description: Choose the normalization strategy (album-wide mode, target level and true-peak ceiling) from analyzer peak, loudness and dynamic-range data. Produces the normalize section of processing_plan.json. Use when planning loudness or level adjustment for a vinyl recording.
---

# Plan Normalize

Choose the strategy, the target and the ceiling. The executor computes the exact
gain deterministically, post-declick and album-wide.

There are **two** decisions here, not one. *How loud* is the target. *How much
room to leave above it* is the ceiling, and it is the one that stops an album
being clipped. A plan that carries only a target is incomplete for every mode
except `album_peak`.

## Inputs

From `analysis.json`:

- `peaks` — `peak_db`, `true_peak_db`, `rms_db`, `gated_rms_db`,
  `crest_factor_db`
- `dynamic_range` — `dr_estimate_db`, `loud_rms_db`, `percentiles`
- `clipping` — `clipped_region_count`, `longest_run_samples`
- `spectral.rumble_db` and `recording_info.dc_offset` — see *Wasted headroom*

Plus `preferences.normalize_mode` and `preferences.normalize_target_db`.

`peak_db` is the largest stored sample; `true_peak_db` is where the waveform
actually goes between samples, which is what a resampler or a lossy encoder will
realise. They can differ by more than a dB on percussive material.

## Decision guide

1. **Default**: `mode: "album_peak"`, `target_db: -1.0`. One gain for the whole
   side preserves the relative dynamics between its tracks — that is the entire
   point of album-wide normalization.
2. `album_gated_rms` when the user wants loudness matching across a collection.
   Take `target_db` from their stated reference (e.g. −18 dB), not from a guess,
   and **always set `peak_ceiling_db`** — a level target says nothing about where
   the peaks land, and without a ceiling the executor drives the export into a
   clip.
3. `album_rms` only to match a figure someone measured as an ungated full-file
   RMS. It counts the inter-track gaps and the lead-in as programme, so a side
   with long gaps measures quiet and normalizes loud. `album_gated_rms` is the
   mode that does what "match the loudness" means; say in
   `decision.rationale` why you did not use it.
4. `track_peak` is discouraged: it flattens the level relationships the record
   was mastered with. Use it only for compilations assembled from genuinely
   mismatched sources, and say so in `decision.rationale`.
5. **Skip** (`"enabled": false`, or `mode: "none"`) when `peak_db` is already
   within 0.5 dB of the target, or when `clipping.clipped_region_count > 0` and
   the gain would be positive — normalizing a clipped capture amplifies the
   damage. Tell the user instead.

### Choosing the ceiling

`peak_ceiling_db` is in **dBTP**, against the 4×-oversampled peak.

- **−1.0 is the right answer almost always.** It is what every streaming platform
  asks for and it is the headroom a later AAC/Opus transcode needs; the encoder
  can add inter-sample peaks that were not in the FLAC.
- Set it on **every** RMS mode. Set it on `album_peak` too whenever
  `true_peak_db - peak_db` is more than about 0.3 dB, because a sample-peak target
  of −1.0 dBFS then lands above −1.0 dBTP.
- Do not set it *below* the target on a peak mode — the ceiling would win and the
  target would be decoration.
- −2.0 if the user has said they transcode to lossy for a car or a phone.

### Wasted headroom

A peak-based gain is limited by the loudest thing in the groove, audible or not.
Two things on a vinyl transfer routinely are not:

- **Rumble** — warp and wow put energy at 0.5–8 Hz that no one hears and that
  still eats the headroom. Read `spectral.rumble_db` against `peaks.peak_db`.
- **DC offset** — `recording_info.dc_offset` shifts the whole waveform toward one
  rail, so one side of it clips early.

There is **no subsonic-filter or DC-blocking stage in the pipeline**, so neither
can be fixed here. What you can do is say it: if the gain comes out smaller than
the music warrants, name the reason in `decision.rationale` so the next person
does not go looking for a bug. A high `rumble_db` is also worth telling the user
about — it is a turntable or a pressing problem, and it belongs upstream in
`vinyl-archive`.

## Output

```jsonc
"normalize": {
  "enabled": true,
  "engine": "native",          // 'ffmpeg' also implements gain, bit-comparably
  "mode": "album_peak",        // album_peak | album_gated_rms | album_rms |
                               // track_peak | none
  "target_db": -1.0,
  "peak_ceiling_db": -1.0,     // dBTP; null leaves the gain uncapped
  "decision": { "skill": "plan-normalize", "rationale": "…", "confidence": 0.95,
                "inputs": ["analysis.json#peaks", "analysis.json#clipping"] }
}
```

Run `vinyl-process lint` before shipping. The findings that belong to this section
are `rms-without-peak-ceiling`, `ungated-rms`, `no-headroom`,
`normalize-clipped-source`, `true-peak-over-full-scale` and
`thin-true-peak-headroom`. None of them is cosmetic.

## Checkpoint

**Ask whether the level should be touched at all.** It is a yes/no question, it
belongs to the person who owns the record, and it is the change they will notice
afterwards. Never carry the default through silently.

Present:

- `peaks.peak_db`, `peaks.true_peak_db`, and the target and ceiling you propose;
- the gain as a *lower bound*: `target - peak_db`. The real value is usually
  larger, because the side's loudest sample is often the stylus drop in the
  lead-in, which the split excludes — on one tested pressing the bound was
  +2.4 dB and the executor applied +8.0 dB;
- for an RMS mode, the same bound from `gated_rms_db`, and a warning that the
  ceiling may cap it;
- for a two-sided album, both sides' `peak_db`, since each plan is normalized on
  its own and the sides can end up at different gains;
- that the exact value appears in `manifest.applied_gain_db` after the run,
  alongside `manifest.applied_true_peak_db`, and that keeping the capture's level
  is `"enabled": false`.

If the answer is yes, **render it before it becomes the album**. Execute into
`review/level/` — the same plan as `review/declick/` with `normalize` switched on,
so the level is the only difference:

```sh
vinyl-process execute plan-side-a.json --audio <recording> \
  -o review/level --manifest manifest-side-a.json
```

This is not an A/B: the level *is* the change, and the louder render always sounds
better, so asking "which do you prefer" is a rigged question. Ask the two things
that a gain can actually get wrong instead:

- has the surface noise come up too far? The gain lifts the noise floor by exactly
  as much as the music, so a quiet pressing with a modest floor survives it and a
  noisy one does not.
- do the quiet passages and the fades still sit where they should relative to the
  loud ones? `album_peak`, `album_gated_rms` and `album_rms` preserve that by
  construction; `track_peak` does not, which is why it is discouraged.

Then read the receipt, not just the audio:

- `manifest.applied_gain_db` against the lower bound you predicted — say so if
  they differ, because they usually do, and by several dB;
- `manifest.applied_true_peak_db`, which is where the album actually ended up;
- `manifest.warnings`. A capped gain and a clipped track both appear there, and a
  capped gain means the target level was **not** reached — re-plan or accept it
  out loud, but do not ship it unmentioned.

## Rules

- Never precompute the gain value. Declick changes peaks slightly, so the
  executor measures after repair; your decision is the *strategy, target and
  ceiling*, and the manifest records the gain that was actually applied.
- `target_db` and `peak_ceiling_db` must be ≤ 0 dBFS. Keep at least 1 dB of
  headroom for lossy transcodes the user may make later — the contract permits
  `0.0` and `lint` will tell you it is a bad idea.
- If the source peaks above the target, the gain is negative — that is normal and
  is not a reason to skip the stage. It also means a clipped-source warning does
  not apply: nothing is being amplified.
- The ceiling wins over the target when they conflict, and the executor warns.
  That is deliberate ([adr/0007](../../../docs/adr/0007-a-level-target-needs-a-true-peak-ceiling.md)),
  not something to work around by raising the ceiling.
- No LUFS. `album_gated_rms` is a level in dBFS measured over the programme, not
  loudness — it has BS.1770's gates and none of its K-weighting
  ([adr/0008](../../../docs/adr/0008-album-gated-rms-is-a-separate-mode.md)). If
  the user asks for −14 LUFS, say what they can have instead.

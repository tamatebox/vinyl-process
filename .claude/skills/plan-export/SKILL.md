---
name: plan-export
description: Choose the export container, bit depth, sample rate, dither and file-naming template for a vinyl rip. Produces the export section of processing_plan.json. Use when planning how processed tracks should be written out.
---

# Plan Export

Decide how the finished audio is written. Archival defaults win unless the user
asked for something else.

## Inputs

- `preferences.export_format`, `preferences.export_bit_depth`,
  `preferences.export_sample_rate`, `preferences.dither`,
  `preferences.track_filename_template`
- `analysis.json#recording_info` — `subtype` and `bit_depth` of the capture.
  `bit_depth` is `null` for a subtype whose width is not a PCM depth, and the whole
  section is absent if its analyzer failed (`analyzers[]` says so). Either way fall
  back on the archival default — 24-bit — and on `source.sample_rate`, and say in
  the rationale that the capture's depth was not known.
- `analysis.json#source.sample_rate`
- `normalize.peak_ceiling_db`, if you are considering a resample — see below

## Decision guide

1. **Container**: `flac` by default (lossless, tags, widely supported). `wav` or
   `aiff` only when a tool in the user's chain needs it; both carry ID3 tags
   here, which some players ignore.
2. **Bit depth**: 16 or 24 — the contract has no other value. Match the capture
   when it is one of the two; a 32-bit or float capture, or one whose `bit_depth`
   came back `null`, exports at **24**, which is the archival default and loses
   nothing anyone can hear. Never *raise* a depth — 16 → 24 adds bytes and no
   information. Reducing 24 → 16 is a deliberate loss and needs the user's word.
3. **Sample rate**: `null` (keep the source rate) for archival. Resample only on an
   explicit request, and to a rate that exists in the wild — 44100, 48000, 88200,
   96000; the contract does not constrain the number, so a typo here is a failed
   run at best. The executor resamples **after** normalizing, and resampling moves
   the peaks, so a plan that resamples needs `normalize.peak_ceiling_db` set: the
   ceiling is held against the 4×-oversampled peak, which is what bounds the sample
   peak of the resampled result. Check it before shipping a resample.
4. **Dither**: quantisation happens exactly once, in `save_audio`, from the float64
   the whole pipeline works in — so it is the *output* depth that decides, not the
   capture's. Once, per file that ships: the review ladder's renders are separate
   runs and each would carry its own quantisation, which is one reason
   [plan-album](../plan-album/SKILL.md) has them rendered wider and undithered
   instead. This section decides the **album's** depth. It does not decide the
   ladder's, and the two differing is expected — predict the difference at the
   final checkpoint so it is not read as a fault. `"none"` at 24 bit: the quantisation floor sits far below any
   pressing's noise floor. `"tpdf"` whenever `bit_depth` is 16, with a fixed
   `dither_seed` so the export stays reproducible.
5. **Naming**: `"{index:02d} - {title}"` by default. Available fields are
   `index`, `title`, `artist`, `album_artist`, `album`, `year`, `position`,
   `catalog_number`. Keep `{index}` in it and use the **same template for both
   sides**: the collision check runs per plan, so two sides sharing an album
   directory can overwrite each other's files without a single lint finding.
   Filenames are sanitised for the filesystem, and `vinyl-process lint` fails on a
   template that renders two identical names within one plan.

## Output

```jsonc
"export": {
  "format": "flac",                 // flac | wav | aiff
  "bit_depth": 24,                  // 16 | 24
  "sample_rate": null,              // null keeps the source rate
  "dither": "none",                 // none | tpdf
  "dither_seed": 0,
  "track_filename_template": "{index:02d} - {title}",
  "write_tags": true,
  "decision": { "skill": "plan-export", "rationale": "…", "confidence": 0.95,
                "inputs": ["vinyl-process.toml#preferences",
                           "analysis.json#recording_info"] }
}
```

## Checkpoint

This section needs no stop of its own. State the outcome in the final summary —
container, bit depth, sample rate, dither, filename template — because the
defaults follow from the capture rather than from taste: keep the source's bit
depth and sample rate, and dither only when reducing depth. Anything else is a
request someone made, so name who asked for it in `decision.rationale`.

## Rules

- The export section has no `enabled` flag: a run always writes files. To skip
  tagging, set `write_tags: false` or disable the `metadata` section.
- Titles come from the `metadata` section; do not duplicate them here.
- Changing `dither_seed` re-rolls the noise, so the output digests change. Leave
  it alone unless the user wants a different noise instance.

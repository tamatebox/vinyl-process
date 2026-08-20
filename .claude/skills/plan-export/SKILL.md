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
- `analysis.json#recording_info` — `subtype` and `bit_depth` of the capture
- `analysis.json#source.sample_rate`

## Decision guide

1. **Container**: `flac` by default (lossless, tags, widely supported). `wav` or
   `aiff` only when a tool in the user's chain needs it; both carry ID3 tags
   here, which some players ignore.
2. **Bit depth**: match the capture. Never *raise* it — 16 → 24 adds nothing but
   bytes. Reducing 24 → 16 is a deliberate loss; if the user wants it, set
   `dither: "tpdf"` with a fixed `dither_seed` so the export stays reproducible.
3. **Sample rate**: `null` (keep the source rate) for archival. Resample only on
   an explicit request; the executor uses polyphase resampling and the plan is
   the record that it happened.
4. **Dither**: `"none"` at 24 bit — it sits far below any pressing's noise floor.
   `"tpdf"` when reducing to 16 bit.
5. **Naming**: `"{index:02d} - {title}"` by default. Available fields are
   `index`, `title`, `artist`, `album_artist`, `album`, `year`, `position`,
   `catalog_number`. Filenames are sanitised for the filesystem, and
   `vinyl-process lint` fails on a template that renders two identical names.

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
  "decision": { "skill": "plan-export", "rationale": "…",
                "inputs": ["vinyl-process.toml#preferences"] }
}
```

## Rules

- The export section has no `enabled` flag: a run always writes files. To skip
  tagging, set `write_tags: false` or disable the `metadata` section.
- Titles come from the `metadata` section; do not duplicate them here.
- Changing `dither_seed` re-rolls the noise, so the output digests change. Leave
  it alone unless the user wants a different noise instance.

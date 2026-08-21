---
name: plan-export
description: Choose the export container, bit depth, sample rate, dither and file-naming template for a vinyl rip. Produces the export section of processing_plan.json. Use when planning how processed tracks should be written out.
---

# Plan Export

Decide how the finished audio is written. Archival defaults win unless the user
asked for something else.

## Outside references

Where a number below is a matter of archival practice rather than of this
codebase, it is cited. Anything here without a citation is an in-house judgement
and should be treated as uncalibrated until someone finds a source for it.

**Rate and depth for an analogue original.** IASA's
[key digital principles](https://www.iasa-web.org/tc04/key-digital-principles)
(TC-04) give the floor: "IASA recommends a **minimum sampling rate of 48 kHz** for
any material", "IASA recommends **96 kHz** as a higher sampling rate, though this
is intended only as a guide, not an upper limit", and "IASA recommends an encoding
rate of **at least 24 bit** to capture all analogue materials" — because 16 bit
"may be inadequate to capture the dynamic range of many types of material,
especially where high level transients are encoded". Read those as constraints on
the **capture**, which is `vinyl-archive`'s business and already fixed by the time
this skill runs. What they settle here is the direction of travel: 24-bit is the
archival figure rather than a generous one, and a 24 → 16 reduction takes the file
*below* the archival minimum, so it is a deliverable being made and not an archive
being written. Say that when someone asks for 16. They also settle why *raising* a
depth is pointless: the recommendation is about what the converter captured, and
16 → 24 cannot retrofit it.

**Container, where the sources disagree — and they do.** IASA names WAV: "IASA
recommends the use of WAVE, (file extension .wav)" and, for archival purposes,
"BWF .wav files [EBU Tech 3285]". This pipeline defaults to FLAC instead, and the
warrant for that is a different document — the British Library's
[FLAC format preservation assessment](https://wiki.dpconline.org/images/f/fe/FLAC_Assessment_v1.0.pdf)
(v1.0, 2018): "**FLAC should be considered a preferred archival format for
audio**. As such, FLAC files should not be converted to WAV if submitted for
repository ingest. Doing so would increase the file's size and remove the internal
checksums which allow for the location of any errors that may already exist in the
file." The same assessment is candid about the other side, and so should you be:
"there is little evidence of memory institutions adopting FLAC, e.g. as an
alternative to lossless options such as WAV or BWF", and the Library of Congress
"describes the adoption levels of FLAC as 'moderate'". So FLAC is a defensible
default rather than the consensus one. If a user's chain wants WAV, they are not
being unreasonable — they are following the other citation.

**Dither, only downwards, and only once.** Audacity's
[dither](https://manual.audacityteam.org/man/dither.html) page states the rule
this section's step 4 implements: "**Dither is only applied when converting from a
higher bit depth to a lower bit depth**", and "Exporting a 16-bit track to 16-bit
with dither set to 'none' will be **lossless**." Sound Forge Pro's
[vinyl-restoration guide](https://soundforgepro.com/sound-forge-pro-for-vinyl-restoration/)
adds the placement: "If you intentionally reduce from 24-bit to 16-bit, **apply
dither once, after all EQ, level and sample-rate changes**." Both are satisfied
here by construction, since quantisation happens exactly once in `save_audio`
after every other stage. And dithering *is* the field's default when the depth
drops — Audacity's
[LP workflow](https://manual.audacityteam.org/man/sample_workflow_for_lp_digitization.html)
step 18 produces "44,100 Hz 16-bit PCM stereo" and notes "**Shaped dither noise
will be applied by default**", so `"tpdf"` at 16 bit is the ordinary choice and
`"none"` at 16 bit is the one that needs a sentence. (Audacity's default is
*shaped* dither; this engine offers TPDF only, which is a narrower choice, not the
same one.)

**Naming.** The `{index:02d} - {title}` default is Audacity step 15's convention
with a separator added: "Edit the labels for the song names — we suggest using
'**01 First Song Name**', '02 Second Song Name'". The zero-padded index first is
the cited part; the ` - ` is ours.

**What is uncalibrated here**: nothing numeric. Every figure this skill states —
48 kHz, 96 kHz, 24 bit, 16 bit, the dither rule, the filename shape — traces to a
citation above. That is unusual among these skills, and it is why a request to
depart from one of them deserves a named reason in `decision.rationale`.

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
- **`normalize.enabled` and its mode, because the depth is downstream of the
  gain.** A gain that is not a power of two moves every sample off the capture's
  quantisation grid, so exporting at the capture's own depth then *re-quantises the
  whole album* and forces a dither decision that keeping the width avoids
  entirely. On a 16-bit capture with `normalize` on, "keep the capture's depth" is
  therefore not the neutral choice it looks like — it is a second quantisation of
  the programme. Decide the depth after the gain, and say which way round you
  reasoned
  ([adr/0019](../../../docs/adr/0019-a-stage-is-parameterised-on-its-own-input.md)).

## Decision guide

1. **Container**: `flac` by default — lossless, tags, and a preferred archival
   format on one citation while WAV/BWF is the recommendation on another (*Outside
   references*). `wav` or `aiff` only when a tool in the user's chain needs it, or
   when they are following IASA rather than the British Library; both carry ID3
   tags here, which some players ignore.
2. **Bit depth**: 16 or 24 — the contract has no other value. Match the capture
   when it is one of the two; a 32-bit or float capture, or one whose `bit_depth`
   came back `null`, exports at **24**, which is the archival minimum for analogue
   material rather than a luxury. Never *raise* a depth — 16 → 24 adds bytes and no
   information, and cannot retrofit an archival capture. Reducing 24 → 16 puts the
   file below that minimum: it is a deliverable, needs the user's word, and gets
   `"tpdf"` with it.
3. **Sample rate**: `null` (keep the source rate) for archival — 48 kHz is the
   cited floor and 96 kHz the cited upper guide, so a capture at either is already
   where it should be and there is nothing to gain by moving it. Resample only on an
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
   final checkpoint so it is not read as a fault. `"none"` at 24 bit — no depth
   is being reduced, and dither is "only applied when converting from a higher bit
   depth to a lower bit depth". `"tpdf"` whenever `bit_depth` is 16, which is the
   documented default in the field when the depth drops, with a fixed `dither_seed`
   so the export stays reproducible. `"none"` at 16 bit is truncation and needs a
   reason in the rationale.
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

Run `vinyl-process lint` before shipping. The findings that belong to this
section are `filename-template`, `filename-collision`, `pointless-dither`,
`resampling` and `speed-and-resample`. The last two are `info`: they say the
audio will be resampled, once or twice, which is a cost to accept knowingly
rather than an error. Leaving `sample_rate` null avoids both.

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

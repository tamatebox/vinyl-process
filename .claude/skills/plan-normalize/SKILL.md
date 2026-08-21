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
except the peak modes: `album_peak` and `track_peak` aim the *sample* peak at
`target_db`, so their target already bounds the peaks. A level target does not, and
`lint` says so (`rms-without-peak-ceiling`, on `album_rms` and `album_gated_rms`).

## Outside references

Where a number below is a matter of LP-transfer practice rather than of this
codebase, it is cited. Anything here without a citation is an in-house judgement
and should be treated as uncalibrated until someone finds a source for it.

**How loud.** Audacity's
[Sample workflow for LP digitization](https://manual.audacityteam.org/man/sample_workflow_for_lp_digitization.html)
step 16: "Use Effect > Normalize...setting 'Normalize maximum amplitude to' to
around **-2 dB** or similar". That is a *peak* target, and "or similar" is the
entire tolerance the source offers — so the defensible band is roughly −1 to
−3 dBFS and this project's −1.0 default sits at its loud edge. The claim that
−1.0 is "what every streaming platform asks for" used to stand here uncited and
has been **removed** rather than softened: a remembered platform spec is the exact
thing this project has already been wrong about. Where the user names a delivery
target, take theirs and cite them.

**Normalize last.** Sound Forge Pro's
[vinyl-restoration guide](https://soundforgepro.com/sound-forge-pro-for-vinyl-restoration/)
puts it at the end of the chain — "Normalize last, if a derivative needs a defined
peak or loudness" — and keeps the two jobs apart: "Peak normalization does not
repair dynamics; loudness normalization changes gain to meet a delivery target."
The executor's order already does this. The citation is why it is not negotiable,
and why a level decision may not be smuggled into an earlier review render.

**One gain, and over what.** A constant gain is what makes a peak mode safe at
all: "Because the same amount of gain is applied across the entire recording, the
signal-to-noise ratio and relative dynamics are unchanged"
([audio normalization](https://en.wikipedia.org/wiki/Audio_normalization)). The
scope of "entire" is the decision, and
[VinylStudio](http://www.alpinesoft.co.uk/vinylstudio/helpfile/filter_settings.htm)
offers the same three this contract does: "normalise each side separately (**the
default**), or adjust **all sides by the same amount**", or "normalise **each
track** separately". Per-track exists in the field, so `track_peak` is not
unheard-of — it is simply the one that discards the mastered relationships. One
plan is one side here, which lands on VinylStudio's *default* rather than on its
all-sides option; that is a known limitation, not a preference, which is why the
checkpoint asks for both sides' post-split peaks.

**Exclude the needle drop and the run-out.** VinylStudio's *smart normalisation*
"ignores audio in the gaps between tracks (as well as before the start of the
first track and after the end of the last)", and its help says why: it "can be
used to prevent the sound of the needle drop and lift from affecting the results".
That is the outside warrant for the two things this skill is most insistent about
— quote the level of the **split** render, not `peaks.peak_db`, and prefer
`album_gated_rms` to `album_rms`. This pipeline arrives there by a different
route, since the split has already discarded the drop and the gap middles before
the executor measures, but the requirement is the same one.

**Loudness, and the one number here with an external oracle.**
[ITU-R BS.1770](https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.1770-5-202311-I!!PDF-E.pdf)
defines loudness as `−0.691 + 10·log10(Σ Gᵢ·zᵢ)` over K-weighted, channel-weighted
mean squares, on 400 ms blocks at 75 % overlap with an absolute gate at −70 LKFS
and a relative gate 10 LU under the absolute-gated result.
[EBU R 128](https://tech.ebu.ch/docs/r/r128v4_0.pdf) sets the delivery target at
**−23.0 LUFS**, and [EBU Tech 3341](https://tech.ebu.ch/docs/tech/tech3341.pdf)
publishes the readings a compliant implementation must produce, to **±0.1 LUFS**.

`album_lufs` implements that, and it is tested against Tech 3341's cases 1-6 at two
sample rates — the only measurement in this project with a correctness oracle
outside it
([adr/0014](../../../docs/adr/0014-album-lufs-ships-with-its-conformance-tests.md)).
So when a user asks for −14 LUFS or −23 LUFS, you can now give them the number they
asked for rather than an approximation of it. Two things still to say out loud:
−23 is a *broadcast* delivery target and has nothing to do with LP practice, and
streaming figures circulate widely as platform specs — **do not quote one from
memory**, take it from the user or from the platform's own document.

**The other school, which this pipeline cannot join.**
[ReplayGain](https://en.wikipedia.org/wiki/ReplayGain) leaves the samples alone
and writes the figure as a tag — its utilities "usually add metadata to the audio
files without altering the original audio data" — and its album mode "calculates
shared peak and gain values across an entire album, preserving the intended volume
differences between tracks", which is `album_peak`'s goal reached without touching
the audio. There is no ReplayGain field in the `metadata` contract and no stage
that would write one, so it is not available here. If someone asks for it, say
that rather than approximating it with a gain.

**Uncalibrated numbers in this skill**, named so nobody mistakes them for
practice: the **−9 LUFS** line above which `lint` calls an `album_lufs` target
unreachable, the **0.5 dB** proximity at which the stage is not worth running, the
**0.3 dB** `true_peak_db − peak_db` gap that triggers a ceiling on a peak mode,
and the "keep at least **1 dB**" floor under *Rules*. All in-house. Only the
target band is cited — and note that the band is a band of *targets* in dBFS, so
it does not transfer to a ceiling in dBTP, which is why this skill no longer names
a ceiling for a lossy transcode.

## Inputs

From `analysis.json`:

- `peaks` — `peak_db`, `true_peak_db`, `rms_db`, `gated_rms_db`, `lufs`,
  `crest_factor_db`
- `dynamic_range` — `dr_estimate_db`, `loud_rms_db`, `percentiles`
- `clipping` — `clipped_region_count`, `longest_run_samples`
- `spectral.rumble_db` and `recording_info.dc_offset` — see *Wasted headroom*

Plus `preferences.normalize_mode`, `preferences.normalize_target_db` and
`preferences.normalize_peak_ceiling_db` — the user's ceiling, `-1.0` by default and
`null` to ask for an uncapped gain. Start from it; the guidance below is why that
default is usually right, not a reason to override a stated preference.

`peak_db` is the largest stored sample; `true_peak_db` is where the waveform
actually goes between samples, which is what a resampler or a lossy encoder will
realise. They can differ by more than a dB on percussive material.

Three of these can be missing, and each changes what you may claim:

- **no `peaks` section** (its analyzer failed — `analyzers[]` says so): you have no
  reference at all. Re-run `analyze --analyzers peaks`; do not plan a level from the
  other sections.
- **`true_peak_db` is `null`** (the recording is too short to oversample): you
  cannot check the sample peak against the reconstructed one, so set the ceiling
  rather than reasoning about whether it is needed.
- **`gated_rms_db` is `null`**: an RMS bound has to come from `rms_db` instead,
  which counts the gaps and therefore reads low. `lint` makes the same substitution;
  say in the rationale that you used it.
- **`lufs` is `null`** (the recording is shorter than one 400 ms gating block, so
  BS.1770 has nothing to measure): you cannot predict an `album_lufs` gain. Use a
  different mode or say the prediction is unavailable.

`lufs` is loudness in LUFS and `gated_rms_db` is a level in dBFS, on the same
blocks and the same gates. They differ by the K-weighting's verdict on this
material's spectrum — a bright side reads louder in LUFS than its level suggests, a
bass-heavy one quieter — so **never substitute one for the other**, and never
subtract them and call the difference anything.

## Decision guide

1. **Default**: `mode: "album_peak"`, `target_db: -1.0`. One gain for the whole
   side leaves "the signal-to-noise ratio and relative dynamics unchanged" — that
   is the entire point of album-wide normalization, and the one property a
   per-track gain gives up.
2. `album_gated_rms` when the user wants loudness matching across a collection.
   Take `target_db` from their stated reference (e.g. −18 dB), not from a guess,
   and **always set `peak_ceiling_db`** — a level target says nothing about where
   the peaks land, and without a ceiling the executor drives the export into a
   clip.
3. **`album_lufs` when the user names a figure in LUFS**, which is the only time
   it is the right answer — it is a broadcast and streaming convention, not an LP
   one. Take `target_db` from what they said (it is **in LUFS** on this mode, not
   dBFS) and **always set `peak_ceiling_db`**: a loudness target says nothing about
   peaks, and −14 LUFS on dynamic material will be capped. Predict the gain from
   `peaks.lufs`, saying that it is a whole-recording figure and the executor
   re-measures on the cuts. Do not offer this mode to someone who did not ask for
   LUFS.
4. `album_rms` only to match a figure someone measured as an ungated full-file
   RMS. It counts the inter-track gaps and the lead-in as programme, so a side
   with long gaps measures quiet and normalizes loud. `album_gated_rms` is the
   mode that does what "match the loudness" means; say in
   `decision.rationale` why you did not use it.
5. `track_peak` is discouraged: it flattens the level relationships the record
   was mastered with. It is a documented option in the field rather than a mistake
   (VinylStudio offers "normalise each track separately"), so the argument against
   it is the one above and not novelty — use it only for compilations assembled
   from genuinely mismatched sources, and say so in `decision.rationale`.
6. **Skip** (`"enabled": false`, or `mode: "none"`) when the gain would not be
   worth applying: on a peak mode that is `peak_db` already within 0.5 dB of the
   target, and on an RMS mode `gated_rms_db` (or `rms_db`, if that is `null`) within
   0.5 dB of it. Skip too when `clipping.clipped_region_count > 0` and the gain
   would be positive — normalizing a clipped capture amplifies the damage. Tell the
   user instead.

### Choosing the ceiling

`peak_ceiling_db` is in **dBTP**, against the 4×-oversampled peak. Take
`preferences.normalize_peak_ceiling_db` as the starting value and depart from it
only for a reason you can name.

- **−1.0 is the default, and is inside the cited band** (−1 to −3 dBFS, from
  Audacity step 16) at its loud edge. What is *not* cited is any platform spec —
  see *Outside references*. The reason to keep a dB in hand is mechanical rather
  than editorial: a later AAC/Opus transcode reconstructs the waveform and can put
  inter-sample peaks where the FLAC had none. Say that, not a platform name.
- Set it on **every** RMS mode, even if the preference says `null`: an uncapped
  level target is the one combination that can drive the export into a clip. Set it
  on `album_peak` too whenever `true_peak_db - peak_db` is more than about 0.3 dB,
  because a sample-peak target of −1.0 dBFS then lands above −1.0 dBTP — and set it
  when `true_peak_db` is `null`, since then you cannot know that it is not.
- Do not set it *below* the target on a peak mode — the ceiling would win and the
  target would be decoration.
- **Lower it when the user transcodes to lossy**, because the encoder
  reconstructs the waveform and can lift inter-sample peaks above where the FLAC
  sat. **How much lower, no source here says.** Audacity's −2 dB is the same
  number but a different quantity — a peak *target* in dBFS, not a true-peak
  ceiling in dBTP — so the citation does not carry across. Pick a value inside the
  cited −1 to −3 band, name the transcode in the rationale, and say the figure was
  chosen rather than sourced.

### Wasted headroom

A peak-based gain is limited by the loudest thing in the groove, audible or not.
Two things on a vinyl transfer routinely are not:

- **Rumble** — warp and wow put energy at 0.5–8 Hz that no one hears and that
  still eats the headroom. `spectral.rumble_db` is what is below 40 Hz *relative to
  the whole recording* — 20·log10 of the amplitude ratio, so it is ≤ 0 and is not a
  level in dBFS. −48 dB is negligible; −20 dB is a tenth of the amplitude (1 % of
  the energy) in a band nobody can hear. Compare it with the other entries of
  `spectral.bands`, which are computed the same way, and never with
  `peaks.peak_db` — that is a different quantity.
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
                               // album_lufs | track_peak | none
                               // target_db is in LUFS on album_lufs, dBFS elsewhere
  "target_db": -1.0,
  "peak_ceiling_db": -1.0,     // dBTP; null leaves the gain uncapped
  "decision": { "skill": "plan-normalize", "rationale": "…", "confidence": 0.95,
                "inputs": ["analysis.json#peaks", "analysis.json#clipping"] }
}
```

Run `vinyl-process lint` before shipping. The findings that belong to this section
are `rms-without-peak-ceiling`, `ungated-rms`, `no-headroom`,
`normalize-clipped-source`, `true-peak-over-full-scale`,
`thin-true-peak-headroom` and, on `album_lufs` alone, `lufs-target-is-loud`.
None of them is cosmetic.

## Checkpoint

**Ask whether the level should be touched at all.** It is a yes/no question, it
belongs to the person who owns the record, and it is the change they will notice
afterwards. Never carry the default through silently.

Present:

- **the peak of the audio the gain will actually be measured from**, which is the
  split (and declicked) tracks, not the recording. `review/` already holds that
  render by the time this checkpoint runs, so read the peak off it; the executor
  measures the same buffers and never opens `analysis.json`
  ([executor.py](../../../src/vinyl_process/executor.py), `_normalize`);
- the gain that implies: `target - that peak`. With `declick` off it is the value,
  to within rounding, not an estimate;
- `peaks.peak_db` and `peaks.true_peak_db` **only to explain the difference**, and
  only if there is one worth explaining. They describe the whole recording,
  including the lead-in, and on a record the loudest sample of the file is
  routinely the stylus drop — which the split throws away. This section used to ask
  for `target - peak_db` as a "lower bound" and to lead with it: measured once, that
  bound understated the real gain by **5.6 dB**, the whole gap being a needle drop
  that never reaches the album. A number that wrong, presented first, is what the
  person anchors on. The correction is not a caveat underneath it — it is not
  showing it first.

  Where the review render does not exist yet, say that the figure is a bound from
  the whole file and that the real gain will be larger by however loud the stylus
  drop was. Do not present it as the expected gain.
- the target and ceiling you propose;
- for an RMS mode, the same bound from `gated_rms_db` — or from `rms_db`, named as
  such, when it is `null` — and for `album_lufs` the bound from `peaks.lufs`, named
  as loudness rather than level. Either way warn that the ceiling may cap it, in
  which case the target will not be reached;
- for a two-sided album, both sides' post-split peaks, since each plan is
  normalized on its own and the sides can end up at different gains. Compare those,
  not the two `peak_db` values: those are two stylus drops, and how hard the needle
  landed on each side says nothing about the music;
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

Plot it — `python scripts/plot_review.py review/level` — and lead with the
per-track images, not the stacked side one: a stacked view cannot show where a tail
sits in dB or whether a fade stepped, and both have mattered. The figure answers
the second question below outright, and half of
the first: peaks per track show whether anything squashed, and a `track_peak` plan
is visible as every panel reaching the same height. Keep the side figure for
checking that the two sides landed level with each other. See
[plan-album](../plan-album/SKILL.md#looking-at-the-render).

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

- Never precompute the gain value. Every repair stage changes peaks — `declick`
  can take a dB off a side by removing a single tick, `decrackle` less but not
  nothing — so the executor measures after all of them; your decision is the
  *strategy, target and ceiling*, and the manifest records the gain that was
  actually applied.
- `target_db` (dBFS, or a level in dBFS on an RMS mode) and `peak_ceiling_db`
  (dBTP) must both be ≤ 0. Keep at least 1 dB of
  headroom for lossy transcodes the user may make later — the contract permits
  `0.0` and `lint` will tell you it is a bad idea.
- If the source peaks above the target, the gain is negative — that is normal and
  is not a reason to skip the stage. It also means a clipped-source warning does
  not apply: nothing is being amplified.
- The ceiling wins over the target when they conflict, and the executor warns.
  That is deliberate ([adr/0007](../../../docs/adr/0007-a-level-target-needs-a-true-peak-ceiling.md)),
  not something to work around by raising the ceiling.
- **The gain does not branch on the capture's bit depth; its export consequence
  does.** The arithmetic is identical at any depth because the pipeline works in
  float64 and quantises once. Two things follow and both get asked about. First,
  the gain cannot expose the capture's own quantisation noise on a needledrop: a
  16-bit capture carries it near −101 dBFS, the gain lifts it by exactly the gain,
  and the record's surface noise sits tens of dB above it and rises by the same
  amount — so there is no "be conservative on a 16-bit source" rule to apply, and
  inventing one costs level for nothing. Second, what the gain *does* change is
  that every sample leaves the capture's quantisation grid, which turns the export
  depth into a live decision on a 16-bit capture where it was not one before. That
  decision belongs to [plan-export](../plan-export/SKILL.md) step 2, and the answer
  there is still to match the capture — say in the rationale that the gain was
  considered and did not move it, because the obvious wrong turn is to widen the
  export to "protect" a signal whose noise floor is 40-odd dB above the question
  ([adr/0019](../../../docs/adr/0019-a-stage-is-parameterised-on-its-own-input.md)).
- **LUFS is `album_lufs` and nothing else.** `album_gated_rms` remains a level in
  dBFS measured over the programme — BS.1770's gates, none of its K-weighting
  ([adr/0008](../../../docs/adr/0008-album-gated-rms-is-a-separate-mode.md)) — so
  quoting it in LUFS is wrong by however much the K-weighting says. If the user
  asks for a figure in LUFS, use the mode that measures LUFS.

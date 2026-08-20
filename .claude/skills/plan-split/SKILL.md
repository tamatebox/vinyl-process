---
name: plan-split
description: Decide final track boundaries for a vinyl recording by combining analyzer boundary candidates with Discogs/MusicBrainz track counts and durations. Produces the split section of processing_plan.json. Use when planning how to split a recording into tracks.
---

# Plan Split

Choose the final track boundaries. Treat this as an optimisation problem — pick
the boundary set that best explains *all* the evidence — not as "cut at every
silence".

## Outside references

Where a number below is a matter of LP-transfer practice rather than of this
codebase, it is cited. Anything here without a citation is an in-house judgement
and should be treated as uncalibrated until someone finds a source for it.

**Where the boundary goes.** Audacity's
[Sample workflow for LP digitization](https://manual.audacityteam.org/man/sample_workflow_for_lp_digitization.html)
is the closest thing to a documented procedure. Step 14: "If you are using a
2-second gap, adjust the label position as desired to be **0.5 seconds before the
start of the next track**." Step 12 bounds the gap: "Edit the inter-track gap as
desired to around a **maximum of 2 seconds**; you may wish to use a shorter gap
or even **no gap at all** for some recordings."

**That reference practice assumes the margin is silent, and ours is not.** The
same step 12 opens: the gaps "are rarely truly silent so you may want to
**replace them with silence**", and
[VinylStudio](https://www.alpinesoft.co.uk/VinylStudio/helpfile/configure.htm)
has an explicit "**Add Silence**: use these fields to add silence at the start
and / or end of saved tracks", paired with "you should **eliminate the existing
gaps** … possibly **fading the tracks in and out if there is a lot of background
noise**". So the documented workflow cuts the record's own gap away and generates
silence in its place. **This pipeline's `split` stage only cuts** — it cannot
generate — so whatever margin is kept is the record's groove noise at whatever
level the pressing has. Take the 0.5 s placement from the reference; do not
inherit its assumption that 0.5 s is inaudible.

**Fades.** Audacity step 13: "Normally fade outs should be longer (**typically a
few seconds**), and fade ins, if required, **quite short (typically a fraction of
a second)**", and it suggests a curved *Studio Fade Out* over a linear one.
VinylStudio fades the edges when "there is a lot of background noise". Both are a
fraction of a second or more, not the tens of milliseconds a de-click edge fade
needs — the two purposes are different and the numbers do not transfer between
them. See the fade rule under *Rules*.

**Excluding what is not music.** Keeping the needle drop as a deliberate artefact
is a recognised choice ([vinyl rip](https://en.wikipedia.org/wiki/Vinyl_rip)),
and so is removing it; the dead air between the drop and the music is where the
crackle lives. Practitioner advice to trim the needle drop and the run-out
because they can peak above the music matches what this skill's *Rules* require
for `album_peak`'s sake — reported through a search summary of
[VinylEngine](https://www.vinylengine.com/turntable_forum/viewtopic.php?t=125872)
threads that answer 403 to a direct fetch, so treat it as second-hand.

**The tracklist pre-places the cuts, it does not confirm them.** VinylStudio's
[split screen](https://www.alpinesoft.co.uk/VinylStudio/helpfile/split_tracks.htm)
works the way step 1 of *Procedure* does: with looked-up track times "VinylStudio
will have inserted trackbreak markers for you and you will just need to position
them accurately in the gaps between the tracks". Durations position expectations;
the audio places the cut.

**Not applicable, and worth knowing why.** Red Book's two-second gap is the
[pregap](https://en.wikipedia.org/wiki/Pregap) — index 00, *outside* the track,
inserted by the burner — so "2 seconds of leading silence inside the track" was
never the convention, and the advice for vinyl-to-CD was to *trim* the record's
gap so it did not add to it. Lossless containers need no padding either: FLAC,
WAV and ALAC are [gapless](https://en.wikipedia.org/wiki/Gapless_playback) by
design, with no encoder delay to compensate, so a leading margin here buys
nothing mechanical and is purely a listening choice.

## Inputs

From `analysis.json`:

- `boundaries.candidates[]` — `{sample, method, confidence}` with methods
  `silence`, `rms_valley`, `spectral_change`
- `boundaries.lead_in_end_sample`, `boundaries.lead_out_start_sample` — the
  playable region; the trailing silence is the run-out groove. **Both are level
  thresholds and both can be wrong.** On material that drops out by design — dub,
  electronic — `lead_out_start_sample` fires at the drop rather than at the
  run-out: on one tested side it landed 22 s before the music stopped, and taking
  it at face value would have truncated the track. `lead_in_end_sample` comes back
  `null` when there is no leading silence to find, and `lead_out_start_sample`
  does the same when the recording ends in music. Check both against
  `periodicity` before trusting either, and read *both* as absent rather than as
  zero: a `null` marker means the side has no detected edge there, which changes
  where track 1 starts and where the last one ends (see Rules).
- `periodicity.windows[]` — the answer to "is this stretch music or surface?",
  which level and spectrum cannot give. See *Surface or programme?* below.
  `programme_period_seconds` and `programme_peak_prominence` are `null` when no
  window lies wholly inside the programme, and the whole section is absent when
  its analyzer failed or was not selected.
- `band_profile.bands[]` — `{low_hz, high_hz, floor_db, values_db}`, the level
  per band over time. The instrument for a **band-limited entrance**, which is
  what broadband level is blindest to. See *Surface or programme?* below.
- `silence.regions[]` — `{start_sample, music_end_sample, music_start_sample,
  end_sample, mean_rms_db, duration_seconds, confidence}`.
  **`music_start_sample`, not `end_sample`, is where the next track begins**: the
  latter is a threshold crossing, so on a track that fades in it fires late and a
  cut placed there loses the entrance. The former is a lower bound and safe.
  It is a lower bound *on the broadband level*, though, which is not the same as
  the start of the music: where a track opens with a filtered element and the bass
  arrives seconds later, `music_start_sample` marks the **bass**. On one 12" both
  sides did exactly that and it cut 3.8 s off one intro and 7.3 s off the other.
  Check it against `band_profile` before using it as the start of a track.
  **`music_end_sample`, not `start_sample`, is
  where the preceding track stopped**: `start_sample` is a fixed-threshold
  crossing, which on a fading track fires mid-fade (4 s early on one track of a
  tested pressing, 22 s on another).
- `rms_profile` — the envelope, when you need to look at a specific stretch
- `source.sample_rate`, `source.num_samples`

Plus the release tracklist: expected track count and per-track durations. If you
have none, ask the user for the track count before guessing.

## Surface or programme?

Every hard boundary on a record comes down to this question, and the two obvious
ways to answer it both fail.

**Level fails** because a quiet outro and a run-out groove sit at the same level.
That is what `lead_out_start_sample` gets wrong.

**Brightness fails, and fails convincingly.** A scuffed lead-in groove is
*bright* — on one tested side it ran 25 dB above the run-out in the 3-8 kHz band,
above the music as well; on another it was 20 dB above. Brightness reads as
programme and it is not: abrasion is impulsive and impulses are broadband. So a
whole-file `spectral` figure settles nothing, and neither does "is this stretch
bright".

What works is not the *tilt* of the spectrum but a **step in one band while its
neighbours hold still**, which is `band_profile`, and a **period**, which is
`periodicity`. Two instruments, for two different questions:

| The stretch in doubt | Read |
|---|---|
| level-matched with a quiet outro or a run-out — is it still the track? | `periodicity` |
| a band-limited entrance the broadband level cannot see | `band_profile` |

**`band_profile` is what finds an entrance.** Surface noise piles its energy into
one band — on a played LP usually the lowest, because unequalised groove noise
rises about 3 dB/octave and RIAA playback then boosts the bass and cuts the
treble — and *that* band sets the broadband level. On one 12" a clean run-out fell
monotonically from -71 dBFS in 40-150 Hz to -93 dBFS in 3-8 kHz. So an intro
sitting 20-30 dB above the surface in 400-3000 Hz moves `rms_profile` by a
fraction of a dB, which is why `silence` misses it. Per band, in one 0.2 s frame:

- the entrance is a **step in a band with its neighbours unmoved** — on that
  record, 400-1000 Hz up 18.5 dB and 1000-3000 Hz up 14.4 dB while 40-150 Hz and
  150-400 Hz did not budge. Crackle cannot make that shape: it is broadband, so it
  lifts several bands at once.
- compare a band against **its own `floor_db`**, never another band's, and treat
  `floor_db` as a percentile of the whole file rather than as the level of
  silence — on a side that is mostly music it *is* a music level, so read steps
  between frames, not absolute headroom.
- a **single frame** that lifts one band is a tick, not an entrance. Require the
  lift to persist.
- the tilt still tells you *which kind* of surface you are looking at — falling
  towards the top means smooth groove noise, a lifted top band means abrasion —
  but never whether the stretch is programme.

**Periodicity is what settles a tail.** A groove defect repeats once per revolution —
1.8 s at 33 1/3 rpm, 1.333 s at 45 — and never on the beat. For a window in
`periodicity.windows[]`:

- compare each `revolution[].r` against the window's own `peaks[0].r`. Where a
  revolution correlation rivals the top peak, the window is the pressing.
- otherwise check that `peaks[0].period_seconds` is `programme_period_seconds` or
  a simple multiple or division of it, and that its prominence above
  `baseline_r` is in the region of `programme_peak_prominence`.
- where nothing correlates strongly — every `r` small, whatever the level — there
  is no music there either. Silence and damage both look like this.

Two readings that look sound and are not. `baseline_r` **is not** a surface
marker: on the same side the crackling lead-in sat at 0.17-0.23 while the
run-out, whose tick is far cleaner, sat at -0.03, and quiet programme reached
0.24. Subtract it, do not threshold on it. And a single correlation taken at
`programme_period_seconds` is not a discriminator either: on a second side the
whole-programme estimate landed on the bar while individual windows expressed
the sub-beat, and the comparison separated nothing.

Expect the beat to show *more* strongly in a quiet passage than in the loud body
of the same track — the surface stops masking it. A faint stretch that locks to
the grid harder than the track does is still that track.

**When periodicity is not available**, this question has no reliable answer here.
The section is absent if its analyzer failed (`analyzers[]` says so) and
`programme_period_seconds` / `programme_peak_prominence` are `null` when no window
sat wholly inside the programme. Re-run `analyze --analyzers silence,periodicity`
first — it is cheap, and so is `analyze --analyzers band_profile` when the doubt
is an entrance rather than a tail. If neither can be had, do not fall back on
level or brightness, which is what this section exists to rule out: keep the
longer cut, drop `decision.confidence` accordingly, and say in the rationale that
the boundary is unconfirmed. Erring long ships fadeable surface noise; erring short truncates a
track.

## Procedure

1. Convert the tracklist durations into expected boundary positions (cumulative
   sums), scaled into the playable region between lead-in end and lead-out start.
   Where either marker is `null`, use the file's own edge in its place (`0` and
   `source.num_samples`) for this scaling only — it positions the *expectations*,
   not the cuts, which come from steps 3–5.
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
   - `start_sample` = the entrance − a margin of about 50 ms, where "the
     entrance" is the gap's `music_start_sample` unless `band_profile` shows a
     band-limited element starting earlier (see *Surface or programme?*), in
     which case it is the first frame of that. Not a fixed pre-roll off
     `end_sample`: the margin a track actually needs varies, and across one album
     it ran from 0.07 s to 0.42 s, so one figure either clips an entrance or ships
     bare surface ahead of it. 50 ms is the floor, not the target — asked to
     judge, one person called 50 ms "stingy" across a whole record and 0.5 s was
     adopted for all three tracks. It is a listening decision like any other, so
     put it to them rather than defending the smallest number that works;
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
   Confirm the cut against `periodicity` past it, not against `rms_profile` — a
   flat plateau at the surface level can be the track itself (a dub side ran 22 s
   of outro through one, with the beat still going, after the level threshold had
   already called it the run-out). Read the windows after your cut: still on
   `programme_period_seconds` means the track is still playing, so extend; taken
   over by `revolution` means the run-out, so the cut stands. See *Surface or
   programme?*.

   **If no silence region opens after the last track began**, the recording ends in
   music or in undetected surface: close it at `source.num_samples`, check the last
   windows of `periodicity` for a run-out that was never detected as silence, and
   record in the rationale that the end is the end of the file. Still do not
   interpolate it from the label's duration.

   The label is a cross-check in one direction only. Report a disagreement over
   ~5 s as a fact about the pressing, not as a reason to move the cut — and do not
   read an *agreement* as confirmation either. On a side whose printed duration was
   12:21, starting the track at the needle drop instead of at the music gave
   12:19.5, and that near-perfect match was the best argument for a boundary 20 s
   wrong. Durations are sums; two errors inside one buy a coincidence cheaply.
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

**Render the cuts as whole tracks and hand them over to be listened to.** A table
cannot settle a boundary. This was tried, and what came back was "I can't tell
without hearing it" — which is right, and the Checkpoint below used to ask for a
table anyway. Write a plan carrying this `split` section with **`declick` and
`normalize` disabled** (leave `metadata` alone — the filenames come from it) and
execute it into a directory of its own. `metadata` is decided *after* this
checkpoint, so unless the tracklist is already in hand and written into
`metadata.tracks`, the filenames come out as `Track 01…` and `lint` says so
(`missing-title`, a warning). That is expected here; do not invent titles to
silence it.

```sh
vinyl-process execute plan-side-a.json --audio <side-a> \
  -o review/split --manifest manifest-side-a.json
vinyl-process execute plan-side-b.json --audio <side-b> \
  -o review/split --manifest manifest-side-b.json
```

Both sides into the *same* directory — the track indices are album-wide, so that
is where the numbering comes out right, and the loud copy below needs to see the
whole album at once.

Then plot it — `python scripts/plot_review.py review/split` — and lead the
checkpoint with `side-a.png` / `side-b.png`, because where the cuts fell is a
question about the whole side. Reach for the per-track image for the boundaries
you flagged; the tails in particular are a hairline in the stacked view. See
[plan-album](../plan-album/SKILL.md#looking-at-the-render) for what the figure
settles and what it cannot — it does not replace the listening this checkpoint is
for, and a clean-looking figure is not an answer to "does it run on too long".

Seconds of compute, and it is the only check that works. Three things to get
right:

- **Disable `normalize`.** The question is whether the cuts are right, not whether
  a level nobody has agreed to sounds good, and leaving it on quietly ships an
  unreviewed decision. Say that the render is therefore quieter than the finished
  album will be, so the volume gets turned up instead of the fades being judged
  as too faint.

  Never satisfy a request for a louder render through the plan. `album_peak` is
  computed per plan, so two sides get two different gains and a step appears
  between them that is not on the record; and back-solving `target_db` from a
  measured peak to make the gains match writes a number that means "+5.15 dB
  here" while reading as a decision about level, then breaks silently the moment
  `declick` is enabled and the measured peak moves. A provisional level is not an
  adopted decision, and the plan holds adopted decisions only.
- **Then make a loud copy, outside the plan.** Do this as a matter of course, not
  only when asked. "Does it run on too long" is a question about whether surface
  noise is audible, and at the un-normalised level it often is not — the tail
  gets approved because nothing could be heard in it. Run this **once, after both
  sides are rendered**, so a single gain covers the whole album:

  ```python
  # Run inline (python - <<'PY'). Do not save this into the job directory:
  # plan-album forbids scripts there, and this is not part of the pipeline.
  import glob, os, numpy as np, soundfile as sf

  # Whatever plan-export chose — do not assume FLAC.
  exts = ("flac", "wav", "aiff", "aif")
  files = sorted(f for e in exts for f in glob.glob(f"review/split/*.{e}"))
  if not files:
      raise SystemExit("nothing in review/split — render both sides first")
  peak = max(np.abs(sf.read(f, dtype="float64", always_2d=True)[0]).max() for f in files)
  gain = 10 ** ((-1.0 - 20 * np.log10(peak)) / 20)
  os.makedirs("review/split-loud", exist_ok=True)
  for f in files:
      x, sr = sf.read(f, dtype="float64", always_2d=True)
      sf.write(f"review/split-loud/{os.path.basename(f)}", x * gain, sr, subtype="PCM_24")
  ```

  One gain for every file, computed across both sides — run it per side and you
  have rebuilt the step you were avoiding. 24-bit so no dither decision is
  implied. Drop a `README.txt` in there saying it is disposable, carries no
  manifest, and that `plan-normalize` has not run. Point the person at
  `review/split/` for the cuts and `review/split-loud/` for the tails, and say
  which is canonical.
- **Whole tracks, not excerpts.** Clips stitched around each cut — tail, dropped
  segment, next entry — look informative and are not: that was tried too, and read
  as unintelligible. People judge a track by playing it.

Alongside the audio, a table, one row per track: position, title, the duration you
cut, the label's duration, and the difference. Then:

- name the evidence each boundary came from (`silence`, `rms_valley`,
  `band_profile`, `periodicity`, or interpolated from durations because nothing
  was detected there);
- explain every difference over ~5 s — the usual causes are a fade the threshold
  cut short and a label duration that does not match the pressing;
- flag any boundary whose `music_end_sample` had to be overridden, and any place
  you went against `lead_in_end_sample` or `lead_out_start_sample`.

Do not move on until the person has listened and agreed, and ask in the terms they
can answer in: for each track, is the beginning clipped, does it end early, does it
run on too long. Never in samples. Say that the last of those is easiest to hear in
`review/split-loud/`, and that the first two read the same in either copy — a flat
gain cannot change the shape of an edge, only whether it is loud enough to notice.

**End with a short list of the specific places to listen to, and why.** Ten tracks
is around 35 minutes, and asking for all of it back gets the whole thing skimmed —
including the two edges that actually needed an ear. You already know which
boundaries are weak: the ones you flagged above. Turn each into one line naming the
file, the copy to play it from, roughly where in it to listen, and the doubt it
settles:

> - `review/split-loud/05 - 不安.flac`, the last 5 seconds — the cut sits 1.8 s
>   past where the level says the music stopped, so there may be audible run-out
>   noise before the fade. Is there?
> - `review/split/03 - 想像.flac`, the first 2 seconds — this entrance was the
>   quietest on the side and the margin ahead of it is the shortest. Is anything
>   missing from the start?

Three or four such lines, ordered by how much the answer would change. Say plainly
that the rest of the album can be spot-checked, and that this list is where the
decision actually rests. Do not pad it with boundaries you are confident about: a
list that includes everything says nothing, which is the failure it exists to
avoid. If genuinely every boundary is strong, say that and name the one you would
still play first.

## Rules

- Positions are integer samples into the *source* file. Never seconds.
- `index` is the track's position on the **album**, not within this plan: side B
  continues where side A stopped (6, 7, …) so both sides export into one directory
  with correct filenames and tags. Indices must be contiguous and ascending;
  tracks must not overlap; the dead middle of a gap stays in neither track.
- Start the first track from the **opening** silence region's `music_start_sample`
  — the region whose `start_sample` is 0 — less the same margin every other track
  gets, and **not** from `lead_in_end_sample`. That
  marker is where the lead-in groove stops, and the needle drop lands *after* it:
  on both sides of a tested pressing the loudest sample of the whole side was the
  drop itself, at −3.4 dBFS between `lead_in_end_sample` and the first gap, against
  −9 dBFS for the loudest music. Starting at the marker puts that pop inside track
  1 and then hands it to `album_peak`, which costs 5.6 dB of gain across the whole
  album. Likewise the last track ends at its own `music_end_sample` (step 5), not
  at `lead_out_start_sample`. Cut *inside* a silence.

  **Two ways the "opening region" is not the one you want**, both met on one 12":

  - *The file opens with digital silence.* Side Y's first region ran 0-1.5 s at
    −88.5 dBFS — the recorder running before the needle landed — and its
    `music_start_sample` marked where the **lead-in crackle** began, 1.3 s in.
    Taking it would have opened the track with 12.5 s of crackle.
    `lead_in_end_sample` sat at the same false edge. Use the region that actually
    precedes the music, which is the next one along, and confirm with
    `band_profile` that what follows it is the music.
  - *There is no region at 0 and `lead_in_end_sample` is `null`.* This rule used
    to conclude "the side begins in music: start at sample 0". On side X of that
    same record it does not: the file opens with the needle drop, a −28 dBFS
    thump, and then 30 s of lead-in groove, and the drop's pop at 8.98 s was the
    loudest sample of the whole side (−3.17 dBFS against −7.45 for the loudest
    music). Starting at 0 would have shipped all of it. So check `band_profile`
    before concluding a side begins in music — every band flat across 20 s, with
    a step of 30 dB in one frame at the end of it, is a lead-in and not an
    entrance — and start from the last silence region before that step.

  What has *not* changed: do not reach past the gap that follows track 1 and start
  there, which would open the album at track 2's entrance.
- **Whatever margin you keep is bare surface, and that is where the clicks are.**
  Nothing masks them there, and the opening grooves are the most handled part of a
  record: on one album the first half-second of a track carried up to 45 times the
  click density of the track itself. Keep the margin because a clipped entrance
  cannot be recovered, but do not expect trimming it to fix a click a listener
  complains about — measured on that album, the audible one was 23 dB louder than
  anything in the margin and sat *after* the music had started. Reaching for a
  longer fade-in instead is worse: it shapes the signal to hide the symptom.
- Titles do not belong here — they live in the `metadata` section. The plan must
  not carry the same string twice.
- **Both edges need a fade, and the length depends on which of two jobs it is
  doing.** A vinyl cut lands in surface noise rather than silence, so a hard edge
  is a step discontinuity and therefore an audible click. Removing *just that*
  takes very little: 20 ms in with 50–80 ms out is enough, and it is the right
  answer when the margin is short enough to be inaudible anyway.

  But the margin is groove noise, not silence, and once it is long enough to hear,
  the fade has a second job — bringing that noise in and out instead of switching
  it on. That is what LP practice fades for, and it asks for far longer: a fade-in
  of "a fraction of a second" and a fade-out "typically a few seconds", applied
  when "there is a lot of background noise" (see *Outside references*). 250 ms in
  and 500 ms out sits inside that guidance and has been adopted on a record here.

  So choose the fade *with* the margin, not independently of it, and say which job
  it is doing. The constraint that survives either way: **keep each fade inside
  its own margin** — the fade-in ending before the entrance and the fade-out
  starting after the music has stopped — so that nothing musical is shaped. A
  fade that reaches into the programme is shaping the record rather than joining
  to it, and *that*, not its length in milliseconds, is the line.
- **A side that plays continuously is the opposite case.** Make the *interior*
  boundaries contiguous (`end_sample` == the next `start_sample`), set the fades at
  those joins to 0, and drop nothing between them: the tracks must concatenate back
  into the recording sample for sample, or every transition gets a dip. The two
  outer edges are not interior joins — the side still has a lead-in and a run-out —
  so the first `start_sample` and the last `end_sample` follow the ordinary rules
  above, fade included. `vinyl-process lint` reports a fade at a contiguous join as
  an `error` (`gapless-fade`); a fade-less cut *into* the recording is the milder
  `hard-cut` warning, so a plan that mixes the two conventions can still lint clean
  — read the findings, do not rely on the exit code alone.

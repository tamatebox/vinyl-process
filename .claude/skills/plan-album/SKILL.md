---
name: plan-album
description: Orchestrate planning for a raw vinyl recording — run the analyzer, apply the plan-* stage skills (prefilter, split, declick, decrackle, mono-merge, speed, normalize, metadata, export), assemble and lint processing_plan.json, then execute it. Use when the user wants to process a raw vinyl recording end to end.
---

# Plan Album

Turn a raw recording into a validated `processing_plan.json`, then execute it.
You are the planning layer: **you decide, Python only measures and executes.**

## Outside references

Where a claim below is a matter of restoration practice rather than of this
codebase, it is cited. Anything here without a citation is an in-house judgement
and should be treated as uncalibrated until someone finds a source for it.

**The order of the stages.** Sound Forge Pro's
[vinyl-restoration guide](https://soundforgepro.com/sound-forge-pro-for-vinyl-restoration/)
states the principle this pipeline's order is an instance of: "**Work from
discrete defects toward continuous ones**", then "Normalize last, if a derivative
needs a defined peak or loudness." Its reason for the first half is mechanical
rather than aesthetic — "**Large clicks can corrupt a noise profile** and make
later processing pump or smear" — so click repair ahead of anything broadband is
not a matter of taste. The same guide is where this project's stated limitation
about de-noise comes from: "The noise print must contain only the steady unwanted
bed: no reverb tail, no room tone that belongs to the recording, no music fading
into silence", and Audacity's
[LP workflow](https://manual.audacityteam.org/man/sample_workflow_for_lp_digitization.html)
step 10 takes that print "from either the lead-in grooves immediately before the
music starts, or from a lead-in between tracks". Both of those are what `split`
throws away, which is why de-noise cannot be a post-split stage here — see
[architecture.md](../../../docs/architecture.md) *Known limitations*.

**Quantise once, and derive the deliverables.** The same guide: "If you
intentionally reduce from 24-bit to 16-bit, **apply dither once, after all EQ,
level and sample-rate changes**." That is the whole argument for rendering the
review ladder wider and undithered — a rung that quantised would be a second
quantisation of the same programme, and the album's own is the one that counts.
[plan-export](../plan-export/SKILL.md) owns the album's depth; this ladder is not
the place to decide it.

**A listening copy is a different object from the master.** IASA's guidelines
describe the archival strategy as "copying vulnerable original tapes to sturdy
studio tapes and to making **listening copies** for recordings in frequent demand"
([handling and storage](https://www.iasa-web.org/book/export/html/3812)). Note
what that citation is and is not: it is about physical carriers, and the analogy
to a review render is **ours**. What it supports is that a separate audition class
is normal archival practice; it does not license any particular depth or rate for
one. The claim that "mastering practice approves a high-resolution master and
derives each deliverable from it" stood here uncited and has been narrowed to the
dither citation above, which is the part that has a source.

**Uncalibrated numbers in this skill**: the **~5 s** per-track difference a
checkpoint must explain, and the **~1 dB** between two sides' gains worth noting in
`notes`. Both in-house thresholds for *when to say something*, not for what to do —
which is the only kind of number this skill should carry, since every dial belongs
to a stage skill.

## How to run it

Work through the steps below **one at a time, stopping at every checkpoint**. A
checkpoint is not a progress report: it is a decision handed back to the person
who owns the record. Do not start the next step until they have answered.

Stop where a wrong answer cannot be spotted later by looking at the output. Track
boundaries, declick strength and whether the level is touched at all are exactly
that: by the time there are ten tagged FLACs, verifying them means listening to
the whole side.

A checkpoint that dumps data is not a checkpoint. Show a small table and the one
question that matters. Where the checkpoint is about audio, the audio is part of
the checkpoint — see plan-split, whose boundaries cannot be judged from a table.

**Where the checkpoint is about audio, end it by naming what to listen to.** Not
"here are ten files" — three or four lines, each giving the file, which copy to
play it from, roughly where in it, and the doubt it settles. Handing over a whole
album and asking "does this sound right" gets it skimmed, and the one edge that
needed an ear is the one that gets skimmed past. You already know which decisions
were close; those are the list. Say that the rest can be spot-checked.

## Where the files live

One directory per record, holding everything about it and nothing else:

```
<job-dir>/
  <recording>.flac            the capture, one file per side, name untouched
  analysis-<stem>.json        one per recording, named after it
  plan-<side>.json            one per recording — plan-side-a.json, plan-side-b.json
  review/                     renders made to answer a checkpoint
    split/                      split only                    → checkpoint 2
    prefilter/                  + prefilter, when enabled     → its own checkpoint
    declick/                    + declick                     → checkpoint 3
    decrackle/                  + decrackle, when enabled     → its own checkpoint
    mono/                       + mono_merge, when enabled    → its own checkpoint
    level/                      + normalize                   → checkpoint 4
      plots/                      the figures for that render (see below)
  album/                      the finished tracks + manifest-side-<side>.json
```

Every render also writes **the plan that produced it**, beside its manifest:
`manifest-side-a.json` is paired with `manifest-side-a.plan.json`. The rungs share
one `plan-<side>.json`, which you edit between them, so that file only ever holds
the *last* thing tried — the copies are where the earlier rungs survive. **Quote a
rung's parameters from its copy, never from the plan file**, and when a rung wins,
say which copy it was: a digest cannot be read backwards, and four declick
thresholds have already been rendered, judged and lost this way
([adr/0018](../../../docs/adr/0018-the-receipt-retains-the-plan-that-produced-it.md)).
The audio under `review/` is throwaway; those copies are not.

A single-file album collapses this to `analysis.json`, `processing_plan.json`,
`review/`, `album/` and `manifest.json`. The commands below are written for
whichever case the surrounding text is about, so **substitute the names
consistently**: a two-sided job runs every command twice, once per side, with its
own `analysis-<stem>.json`, `plan-<side>.json` and `--manifest`. Recordings are
never committed — keep the job directory out of version control (this repository
gitignores `jobs/`).

**Each review render adds exactly one stage to the one before it.** That is the
point of the ladder: every comparison then isolates a single decision, so "is the
repair an improvement" is answered by `review/declick/` against `review/split/`
and nothing else differs between them. Build each one by disabling the stages it
has not reached yet and executing into its own directory:

| Render | `prefilter` | `declick` | `decrackle` | `mono_merge` | `split` | `normalize` |
|---|---|---|---|---|---|---|
| `review/split/` | **off** | **off** | **off** | **off** | on | **off** |
| `review/prefilter/` | on | **off** | **off** | **off** | on | **off** |
| `review/declick/` | as decided | on | **off** | **off** | on | **off** |
| `review/decrackle/` | as decided | as decided | on | **off** | on | **off** |
| `review/mono/` | as decided | as decided | as decided | on | on | **off** |
| `review/level/` | as decided | as decided | as decided | as decided | on | on |

`review/prefilter/` is a rung only when the stage is enabled at all; on a record
that leaves it off, the ladder starts at `review/split/` as before. Once it is
enabled it stays enabled on every rung above it, which is what keeps each
comparison a single-stage difference.

`metadata` stays enabled throughout — the filenames are rendered from it — and
`export` has no switch at all.

**Render the ladder at the capture's depth or wider, with `dither: "none"`, and
say so at every checkpoint that uses it.** The ladder runs before `plan-export`
does, so its rungs cannot match the album and should not pretend to. The two ways
of trying both fail: 16-bit *with* dither means choosing the dither at checkpoint
2, before the skill that owns it has run, which is the smuggled decision this
ladder exists to prevent; 16-bit *without* dither is truncation, and it puts
signal-correlated distortion into exactly the quiet tails and fades the person is
being asked to judge. A wider render adds nothing and quantises nothing, so what
they hear is the stage under review and only that.

This is the ordinary shape of the work rather than a compromise — dither is
applied once, after every level and rate change, and an audition copy is its own
class of object (*Outside references*). What it costs is that the person approves
something that is not byte-for-byte what ships, and the answer to that is *not* to
make them identical — it is to **verify** the deliverable against the spec rather
than re-audition it: the depth and rate are what the plan asked for, dither ran
once, and `vinyl-process verify` proves the run reproduces. That is checkpoint 7's
job.

Say the difference out loud each time, in the checkpoint and not only in the
plan's `rationale`. Burying it there is how it went unmentioned for three
checkpoints on the album this rule came from.

```sh
vinyl-process execute plan-side-a.json --audio <recording> \
  -o review/declick --manifest manifest-side-a.json
```

Two things this ladder is protecting against:

- **An unfair A/B.** Two renders at different levels cannot be compared by ear —
  the louder one wins whatever else is true. Keeping `normalize` off until
  `review/level/` is what makes the declick comparison mean anything.
- **An unreviewed decision riding along.** A render made to answer one question
  must not quietly apply the answer to a later one. This is how a level nobody
  agreed to reaches the person's ears as though it were settled.

`review/level/` is not a quality A/B — the level *is* the change. It answers a
different question: is this the level you want, and has the surface noise come up
too far with it.

`review/split-loud/` is not a rung on the ladder at all. It is `review/split/`
with one flat gain applied outside the plan, so that a tail is loud enough to
judge; nothing is ever compared against it and it carries no manifest. See
[plan-split](../plan-split/SKILL.md). Delete `review/` once `album/` is agreed —
the ladder and its figures run **four to five times the size of the album**:

```sh
python scripts/clean_job.py jobs/<record>            # what would go
python scripts/clean_job.py jobs/<record> --delete
```

It lists rather than deletes unless told, removes from an allow-list so anything
it does not recognise is reported and left alone, and refuses while `album/`
cannot stand in for what is being deleted — every manifest's outputs must exist
and still match their recorded digests. Nothing makes it touch a recording, a
plan or an analysis.

## Looking at the render

**Plot every render, as you make it.** One command per rendered directory, no
dependency to install, a few seconds:

```sh
python scripts/plot_review.py review/level
```

It writes `<render>/plots/`: one `side-<x>.png` per recording — every track of that
side stacked — and one image per track named after the track. Each image is a
linear waveform (full scale, so clipping and squashing show) over a dB panel
(0 to −80 dBFS, peak and RMS as lines, so the noise floor, the fades and the tails
show).

**Read both views; they answer different questions.** The side figure is for the
side as a whole — are the cuts where they should be, does one track stand out, do
the two sides sit at the same level. The per-track figure has five times the
vertical resolution and is for one boundary or one tail. This is not a preference:
a stacked view reduces a two-second tail to a hairline and cannot show whether a
long fade descends smoothly or steps. Both are obvious per track.

**Plot the render, not the step.** Do not take a figure before and after each of
the five stages. `metadata` changes no samples, so its pair would be identical;
`export` changes them only if it resamples or dithers. More to the point the
review ladder already does this job better: each rung adds exactly one stage, so
`review/split/plots/` against `review/declick/plots/` isolates the repair and
nothing else, and `declick` against `level` isolates the gain. That is the
property to protect, and a before/after pair inside one step only duplicates it.
So: `review/split/`, `review/declick/` when repair is on, `review/level/`, and
`album/` after the final run — three or four sets, each attached to a render.

Which to lead with, per checkpoint:

| Checkpoint | Lead with | Compare against |
|---|---|---|
| 2 split | `side-*.png` | — |
| 3 declick | per-track | the same track in `review/split/plots/` |
| 4 level | per-track | the same track in `review/declick/plots/` (or `split/`) |
| 7 the album | per-track of `album/` | `review/level/plots/` — they should match unless export resampled or dithered; if they differ, say what did it |

**What a figure settles, and what it does not.** It settles: whether anything
clipped or got squashed against the rail; whether the level relationships between
tracks survived (a `track_peak` plan makes every panel the same height, which is
the mistake made visible); whether every fade is intact and no entrance is
missing; where a tail sits in dB and how far below the programme; whether the two
sides landed at the same level. It settles none of: whether surface noise is
*objectionable*, whether a click is audible, whether a repair dulled an attack,
whether the record sounds right. Those need ears, and a figure that looks clean is
not a reason to skip the listening the checkpoint asks for. Say which of the two
you are reporting — "nothing a figure can detect went wrong" is an honest and
useful sentence; "it looks fine" pretending to cover both is not.

**No scripts in the job directory.** A Python file there is the planning layer
written in Python, which is the one thing this project does not do, and it is
invisible to every check the repository has — see
[adr/0011](../../../docs/adr/0011-a-job-directory-holds-no-scripts.md), which
records the side that shipped with 11 s of run-out groove noise appended because
the only account of how the boundaries got there was a script nobody reviewed. The
plan is the record of the decisions and `decision.rationale` is where the reasoning
goes.

## Procedure

### 1. Measure

```sh
vinyl-process analyze <recording> -o analysis.json
```

Read `analyzers[]` first: a section is absent when its analyzer failed, and every
decision below must cope with that rather than assume a field exists.

> **Checkpoint 1 — is this transfer worth processing?**
> Duration; sample rate, bit depth and `recording_info.channel_balance_db` /
> `channel_correlation`; `peaks.peak_db`; `clipping.clipped_region_count`;
> `surface_noise.noise_floor_db`; the number and length of the silent gaps; and
> for a multi-file album, **which file is which side** and how you concluded it.
> `bit_depth` is `null` on a float capture and the two channel figures are `null`
> on a mono one — report `null` as `null`, never as a number you inferred.
> Ask before planning anything: a clipped or mis-wired transfer should be
> re-recorded, not processed.
>
> **Ask for the Discogs or MusicBrainz release in the same breath.** Not at
> checkpoint 5 — here, at the first exchange, because everything from checkpoint 2
> onward needs the tracklist and the person holding the record can read the
> catalogue number off the sleeve in seconds. Say what you need it for and what you
> cannot get without it: the pressing's label, catalogue number, country and year,
> and the titles **as this pressing prints them**.
>
> Do not proceed on a tracklist from anywhere else. A discography site gives you
> the album, never the pressing, and the difference is not academic: a
> non-authoritative tracklist has come back **nine titles right out of ten**, with
> the tenth wrong by a single character — a different word — and one duration out
> by 6 s. Both were already burnt into the review filenames the person had been
> listening to for two checkpoints. Nine right is what makes this failure quiet.
> If they cannot supply an ID, say the tracklist is provisional every time you show
> it, and keep `metadata.decision.confidence` low until it is settled.

### 2. Gather context

- Release identity: artist/album, or a Discogs/MusicBrainz release ID or URL.
  Prefer an explicit ID — pressings differ.
- User preferences: `vinyl-process config show`. These are defaults for your
  decisions, not commands to the executor.
- Tracklist with per-track durations, when a release is known.

### 3. Decide each section, checking in after each one

The order is the pipeline's, and the pipeline's is practice's: discrete defects
before continuous ones, level last (*Outside references*).

| Order | Section | Skill | Phase |
|---|---|---|---|
| 1 | `prefilter` | [plan-prefilter](../plan-prefilter/SKILL.md) | pre-split |
| 2 | `split` | [plan-split](../plan-split/SKILL.md) | — |
| 3 | `declick` | [plan-declick](../plan-declick/SKILL.md) | pre-split |
| 4 | `decrackle` | [plan-decrackle](../plan-decrackle/SKILL.md) | pre-split |
| 5 | `mono_merge` | [plan-mono-merge](../plan-mono-merge/SKILL.md) | pre-split |
| 6 | `speed` | [plan-speed](../plan-speed/SKILL.md) | pre-split |
| 7 | `normalize` | [plan-normalize](../plan-normalize/SKILL.md) | post-split |
| 8 | `metadata` | [plan-metadata](../plan-metadata/SKILL.md) | post-split |
| 9 | `export` | [plan-export](../plan-export/SKILL.md) | post-split |

**Decide in that order; the executor runs in its own.** `prefilter` and `declick`
act on the whole side before the cuts, but `split` is decided second because
`plan-declick`'s checkpoint counts the detections that fall *inside* the exported
cuts, which needs the boundaries. Deciding a stage and running it are different
orders, and only the second one is
[adr/0012](../../../docs/adr/0012-the-executor-has-a-pre-split-phase.md).

**Route past a disabled stage in one line, not with a checkpoint.** `prefilter`
, `decrackle`, `mono_merge` and `speed` are all off by default and most records
should leave them off; "prefilter: off, rumble is −48 dB and there is no DC offset",
"decrackle: off, the complaint is discrete ticks rather than texture" and
"mono_merge: off, this is a stereo pressing" are the whole of each. Open a
checkpoint only when a measurement, or the listener's own description, argues for
the stage. A checkpoint per stage regardless of whether the stage does anything is
how an eight-stop flow becomes a flow nobody reads.

**The repair rate is in the receipt now.** Each repair stage's `detail` in
`manifest.json` carries `repaired N of M samples (1 in K)`, which is the figure the
practitioner band is stated in — 1 in 200 "suspicious", 1 in 1000-2000 the typical
floor. Quote it at checkpoints 3 and the decrackle one instead of diffing rendered
directories, and quote **both** stages when both ran: the band covers the pair.

**Everything after `split` is about the audio that survives the cuts, and
`analysis.json` measures the whole recording.** The two are not the same file, and
the gap is not small: a side's loudest sample is usually the stylus drop, and its
densest crackle is the lead-in and the run-out — none of which reach the album.
Reading a whole-file figure as though it described the album has produced a
predicted gain **5.6 dB** wrong and a repair workload overstated **fourfold**, on
one pressing, both from numbers these skills asked for by name. Before quoting any
measurement at a checkpoint, ask whether it describes what will be exported; where
it does not, either restrict it to the cuts or say plainly which one it is.

Each stage skill states what its own checkpoint must show. In short:

> **Checkpoint 2 — the track list.** Measured duration against the label's, with
> the difference per track, and every difference over ~5 s explained.
>
> **Checkpoint 3 — repair or not.** The click rate in the gaps against the rate
> under the programme, and how many spans a repair would interpolate.
>
> **Checkpoint 4 — is the level to be touched at all?** This is a yes/no question
> and it is theirs, not yours. Quote the target and the reference the chosen mode
> measures against — `peaks.peak_db` for a peak mode, `peaks.gated_rms_db` for an
> RMS one — and give the gain as *at least* `target - reference`: usually larger,
> because the side's loudest sample is often the stylus drop in the lead-in, which
> the split excludes. Say in the same breath that `normalize.peak_ceiling_db` can
> cap it, in which case the applied gain comes out *below* that bound and the target
> level is not reached. Never present normalization as a default that needs no
> answer.
>
> **Checkpoint 5 — the release.** Label, catalogue number, country, year and the
> tracklist you matched, plus how you matched it. A wrong release makes every tag
> wrong.

`export` needs no stop of its own: keep the capture's own bit depth and sample
rate, and state that in the final summary. Anything else is a request, not a
default.

### 4. Assemble

- `source`: copy verbatim from `analysis.json`.
- `analysis`: `{"path": "analysis.json", "sha256": "<sha256 of that file>"}`.
- `created_by`: `"plan-album"`.
- one object per section, each with a `decision` block recording `skill`,
  `rationale`, `confidence` and the `inputs` you consulted.
- `notes`: a short summary of the decisions that were not obvious.
- See `examples/processing_plan.example.json` for the shape and
  `schemas/processing_plan.schema.json` for the formal contract.

### 5. Lint, then get the go-ahead

```sh
vinyl-process lint processing_plan.json --audio <recording> --analysis analysis.json
```

Fix every `error`. Explain or fix every `warning`. `info` findings are
observations — `resampling`, `ungated-rms` — and need no action beyond mentioning
them if they were not deliberate.

Each stage skill names the findings for its own section. The ones that belong to
no stage are yours, because you assembled the blocks they check:
`schema-version`, `missing-audio`, `source-mismatch`, `source-length-mismatch`,
`analysis-mismatch`, `analysis-digest-drift`, `unknown-engine`,
`engine-unavailable` and `engine-capability`. All but `analysis-digest-drift` are
errors. Every one of them means the plan is paired with the wrong file, the wrong
analysis or an engine that will not run it — never that a decision was poor — so
re-derive the block rather than adjusting a stage.

> **Checkpoint 6 — the final gate.** One line per stage with its on/off state and
> what it will do (`split: 5 tracks`, `declick: off`, `normalize: album_peak
> -1.0 dBFS`, `export: FLAC 16-bit/48 kHz`, `metadata: 10 tags`), plus the lint
> result. This is the last point at which nothing has been written.

### 6. Execute and check the receipt

```sh
vinyl-process execute processing_plan.json --audio <recording> -o <album-dir>
```

> **Checkpoint 7 — what actually happened.** From `manifest.json`: the applied
> gain, each stage's status, and the track durations. The manifest is the first
> place the *real* gain appears, so compare it with what you predicted at
> checkpoint 4 and say so if it differs.

Then `vinyl-process verify <album-dir>/<the manifest this run wrote>` to prove the
run reproduces — once per side on a multi-side album.

## Running unattended

If the person explicitly asks for the whole thing without stops, do it — but list
which checkpoints you skipped and what you assumed at each, and put the same list
in `notes`. Never skip checkpoint 4 silently: a changed playback level is the one
decision people notice afterwards and cannot undo without re-running.

## Rules

- Never modify audio yourself and never bypass the executor.
- **The five original sections are always present; the newer ones are optional.**
  `split`, `declick`, `normalize`, `metadata` and `export` are required fields, so
  omitting one is a validation error rather than a way to skip a stage. To skip
  one, set `"enabled": false` — `split`, `declick`, `normalize` and `metadata` each
  have that flag (re-tagging an existing rip = disable the first three). `export`
  does not: a run always writes files, and `"enabled"` inside `export` is a
  validation error because the contract forbids unknown fields. Use
  `write_tags: false` there instead.

  `prefilter`, `decrackle`, `mono_merge` and `speed` are **optional and disabled
  by default**, and every stage added after schema 3.2 will be. That is what keeps the bump minor and every archived plan
  re-executable ([adr/0012](../../../docs/adr/0012-the-executor-has-a-pre-split-phase.md)).
  Write the section out anyway once you have considered it, with the `rationale`
  saying you decided against — an omitted section and a considered "no" are
  indistinguishable in the file otherwise.
- The plan must stand alone: someone with only the recording and the plan must be
  able to reproduce the album exactly.
- **A plan position is always an index into the source recording**, even when
  `speed` has rescaled time: the executor maps positions at the cut and the
  manifest still reports the source index
  ([adr/0016](../../../docs/adr/0016-a-pre-split-stage-may-remap-time.md)). So a
  boundary agreed at checkpoint 2 survives a speed correction decided afterwards.
  What does *not* survive is a **duration** quoted from `analysis.json`: the
  analyzer measured the uncorrected transfer, so say which timeline a figure is in
  whenever `speed` is enabled.
- One recording per plan. A two-sided album is two recordings, two analyses and
  two plans exported into the same album directory:
  - side B's `split.tracks[].index` continues the album numbering (6, 7, …) and
    both plans set `metadata.total_tracks`;
  - each run gets its own receipt: `--manifest manifest-side-a.json`;
  - `album_peak` is computed per plan, so check the two sides' `peaks.peak_db`
    against each other and say so in `notes` if they differ by more than ~1 dB —
    the sides will end up at slightly different gains.

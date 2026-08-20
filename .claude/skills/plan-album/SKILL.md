---
name: plan-album
description: Orchestrate planning for a raw vinyl recording — run the analyzer, apply the plan-split/plan-declick/plan-normalize/plan-metadata/plan-export skills, assemble and lint processing_plan.json, then execute it. Use when the user wants to process a raw vinyl recording end to end.
---

# Plan Album

Turn a raw recording into a validated `processing_plan.json`, then execute it.
You are the planning layer: **you decide, Python only measures and executes.**

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
  review/                     renders made to answer a checkpoint; throwaway
    split/                      split only                    → checkpoint 2
    declick/                    split + declick               → checkpoint 3
    level/                      split + declick + normalize   → checkpoint 4
      plots/                      the figures for that render (see below)
  album/                      the finished tracks + manifest-side-<side>.json
```

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

| Render | `split` | `declick` | `normalize` |
|---|---|---|---|
| `review/split/` | on | **off** | **off** |
| `review/declick/` | on | on | **off** |
| `review/level/` | on | on | on |

`metadata` stays enabled throughout — the filenames are rendered from it — and
`export` has no switch at all.

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
[plan-split](../plan-split/SKILL.md). Delete `review/` once `album/` is agreed; on a 35-minute album
each render is around 175 MB.

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
on the album this was written from, the stacked view reduced a 2.2 s run-out tail
to a hairline and could not show whether a long fade descended smoothly or
stepped. Both were obvious per track.

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
written in Python, which is the one thing this project does not do. The plan is
the record of the decisions and `decision.rationale` is where the reasoning goes;
a one-off script that emits the boundaries hides them from review instead. One
lived in a job directory here, hard-coded the gap positions as seconds, never
looked at `boundaries.candidates`, and shipped a side with 11 s of run-out groove
noise appended — and because the script was the only account of how it got there,
nothing caught it.

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
> the album, never the pressing, and the difference is not academic: on the record
> this instruction was added for, a Wikipedia tracklist got nine titles right and
> the tenth wrong by one character — 墮落 for the printed 墜落, a different word —
> and one duration wrong by 6 s. Both were already burnt into the review
> filenames the person had been listening to for two checkpoints. If they cannot
> supply an ID, say the tracklist is provisional every time you show it, and keep
> `metadata.decision.confidence` low until it is settled.

### 2. Gather context

- Release identity: artist/album, or a Discogs/MusicBrainz release ID or URL.
  Prefer an explicit ID — pressings differ.
- User preferences: `vinyl-process config show`. These are defaults for your
  decisions, not commands to the executor.
- Tracklist with per-track durations, when a release is known.

### 3. Decide each section, checking in after each one

| Order | Section | Skill |
|---|---|---|
| 1 | `split` | [plan-split](../plan-split/SKILL.md) |
| 2 | `declick` | [plan-declick](../plan-declick/SKILL.md) |
| 3 | `normalize` | [plan-normalize](../plan-normalize/SKILL.md) |
| 4 | `metadata` | [plan-metadata](../plan-metadata/SKILL.md) |
| 5 | `export` | [plan-export](../plan-export/SKILL.md) |

**Everything after `split` is about the audio that survives the cuts, and
`analysis.json` measures the whole recording.** The two are not the same file, and
the gap is not small: a side's loudest sample is usually the stylus drop, and its
densest crackle is the lead-in and the run-out — none of which reach the album.
Reading a whole-file figure as though it described the album has produced a
predicted gain 5.6 dB wrong and a repair workload overstated fourfold, both on the
same pressing, both from numbers these skills asked for by name. Before quoting any
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
- **All five sections are always present.** They are required fields, so omitting
  one is a validation error, not a way to skip a stage. To skip one, set
  `"enabled": false` on it — `split`, `declick`, `normalize` and `metadata` each
  have that flag (re-tagging an existing rip = disable the first three). `export`
  does not: a run always writes files, and `"enabled"` inside `export` is a
  validation error because the contract forbids unknown fields. Use
  `write_tags: false` there instead.
- The plan must stand alone: someone with only the recording and the plan must be
  able to reproduce the album exactly.
- One recording per plan. A two-sided album is two recordings, two analyses and
  two plans exported into the same album directory:
  - side B's `split.tracks[].index` continues the album numbering (6, 7, …) and
    both plans set `metadata.total_tracks`;
  - each run gets its own receipt: `--manifest manifest-side-a.json`;
  - `album_peak` is computed per plan, so check the two sides' `peaks.peak_db`
    against each other and say so in `notes` if they differ by more than ~1 dB —
    the sides will end up at slightly different gains.

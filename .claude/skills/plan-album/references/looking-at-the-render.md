# Looking at the render

Reference for every checkpoint that hands over audio. Moved out of
[plan-album](../SKILL.md) when that file reached its authoring ceiling; four
stage skills link here, which is what made it reference rather than procedure.

Paths below are relative to the job directory.

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
[adr/0011](../../../../docs/adr/0011-a-job-directory-holds-no-scripts.md), which
records the side that shipped with 11 s of run-out groove noise appended because
the only account of how the boundaries got there was a script nobody reviewed. The
plan is the record of the decisions and `decision.rationale` is where the reasoning
goes.

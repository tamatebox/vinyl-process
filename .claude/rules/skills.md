---
paths:
  - ".claude/skills/**"
---

# Writing a plan-* skill

A skill is where this project's decisions live, so a skill that reads badly is a
defect in the product. `docs/analyzers.md` and `docs/dsp-engines.md` are the
recipes for the other two extension points; this is the recipe for the third.

Why these rules exist and what each one cost is
[adr/0017](../../docs/adr/0017-a-skill-is-authored-against-a-rule-file.md). The
reasoning behind the rest is in `CLAUDE.md`, in `docs/adr/` or in
`docs/architecture.md`. Cite it; do not restate it.

## The two kinds

| Kind | Owns | Required headings |
|---|---|---|
| Stage skill (9) | one `processing_plan.json` section | `## Outside references`, `## Inputs`, `## Output`, `## Checkpoint`, `## Rules` |
| Orchestrator (`plan-album`) | no section | `## Outside references`, `## Rules` |

Shape the middle sections to the decision, not to a template. `## Decision
guide`, `## Procedure`, `## Reading the sweep`, `## What this detector cannot do`
and `## Surface or programme?` are all in use and all correct for their stage.
Add a sixth shape when the stage wants one.

Register the skill in `src/vinyl_process/planning/skills.py`: the section it owns,
what it reads, and a `StageBinding` per executor stage its decisions drive.
Nothing else declares any of it, and a contract test holds the bindings against
the executor's own dispatch. `vinyl-process skills --map` prints the result.

Keep `reads` in step with your `## Inputs` section by hand — no test compares
prose to the registry, and the two had drifted in four skills before anyone
looked.

## Decide; never compute

State the decision and hand the arithmetic to the executor. Where a skill's own
instructions say "never do X yourself; the executor does", that is the rule, not
a preference.

A probe is not evidence. Measuring raw audio while planning is allowed; the
moment a reading changes a decision, promote it to an analyzer with a
ground-truth test and re-derive from `analysis.json`. A plan may cite only what
`analysis.json` records.

## Every number carries its provenance

- Cite it in `## Outside references`, or name it in that section's uncalibrated
  paragraph.
- Say which rank the number came from: a published standard's own test vectors,
  then documented practice, then a measurement on a real transfer, then
  synthesis. Synthesis proves the arithmetic and never the benefit — say so in
  the same sentence, and say what a real pressing would change.
- Cite analogue-ripping practice, not digital mastering or streaming delivery. A
  track's edges here are groove noise at the record's own floor, not digital
  silence.
- Compress one record's measurement to the magnitude of the failure mode. "A
  factor of over 100 on one measured side" belongs here; the pressing, the track
  and the exact dB belong in that album's `processing_plan.json`.
- **Never let prose alone prescribe a parameter value.** A number is allowed to
  exist in a skill when a source gives it, when a model default or a `lint`
  constant already carries it — there the skill's mention is the only warning the
  planner gets that it is uncalibrated — or when it triggers a checkpoint rather
  than a setting. A figure that is none of those three is telling someone what to
  write into a plan on this file's authority alone. Replace it: derive it from
  another decision, redirect to the dial that has a measured readout, or state the
  criterion and require `decision.rationale` to say the value was chosen and not
  sourced.
- A number that came from a different **quantity** does not carry across. A peak
  target in dBFS is not a true-peak ceiling in dBTP; a sensitivity slider is not a
  ratio. Cite the quantity, not just the figure.
- Say **which audio** a figure describes, not just which section. A stage that is
  not first in the executor's order receives the previous stage's output, so its
  `## Inputs` names an analysis of the rung that ends there rather than the
  capture's — or names the invariance that makes the capture safe to read
  (`docs/adr/0019-a-stage-is-parameterised-on-its-own-input.md`).

## Write instructions, not status

"Decide from the record in hand, not from any figure in this file" is durable.
"Nothing here has been tried on a real record" is a sentence nobody deletes, and
it anchors every later reader to the first day. Status belongs in an ADR, which
is never edited after acceptance and therefore reads correctly when stale.

## Say what `lint` will say

Name the `Finding` codes that report on your section, with their severity where
it matters. A finding added to `planning/validation.py` will not find its way
into a skill on its own.

## Positions and defaults

Positions are integer sample indices into the **source**, including after a
pre-split stage rescales time (`docs/adr/0016-a-pre-split-stage-may-remap-time.md`).
Never seconds.

A stage added after schema 3.2 is optional and disabled by default
(`docs/adr/0012-the-executor-has-a-pre-split-phase.md`). `plan-album` routes past
a disabled stage in one line rather than opening a checkpoint for it.

## Checkpoints

A checkpoint hands a decision back, so it is a small table and the one question
that matters — never a data dump. Where the question is about audio, render a
listening copy and name what to listen to: which file, which copy, roughly where,
and the doubt it settles. Accept "it did not help" as an answer; `"enabled":
false` is how that gets recorded.

Where the question is whether your stage *helped*, or which of two candidates is
right, two renders and a timestamp is not a comparison anyone can make. What to
hand over and how to verify it differs by your stage alone is
`presenting-comparisons.md`, beside this file.

## What the tests already carry

`tests/contracts/test_skills.py` checks frontmatter, one owner per section, the
required headings, `## Outside references` with a URL in it, the 500-line
ceiling, that every relative link resolves, and the `lint` mapping — derived from
each finding's own `location`, so it is not a second list to keep in step.

Over 500 lines, move detailed reference into `references/` beside `SKILL.md` and
link to it (`.claude/skills/plan-split/references/`). Do not trim prose to go
green.

Citations, anecdote compression and instruction-versus-status are judgement. No
test covers them, and one that pretended to would be gamed or disabled.

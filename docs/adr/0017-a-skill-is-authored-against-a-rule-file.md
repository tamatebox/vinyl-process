# 0017 — A skill is authored against a rule file, not by imitation

**Status**: accepted

## Context

Two of this repository's three extension points have a recipe: `docs/analyzers.md`
for a measurement, `docs/dsp-engines.md` for an engine. The third — a `plan-*`
skill — had one line in the extension-point table, "the relevant
`.claude/skills/plan-*` skill only", and nothing that said what a skill must
contain. Since [0001](0001-planning-lives-in-coding-agent-skills.md) puts every
subjective decision in a skill, that is the extension point with the least
guidance and the most judgement in it.

Nine skills had nonetheless converged on the same skeleton, by imitation. What
imitation did not carry is the list of things that had gone wrong. Eight failures
had occurred and been fixed by hand:

1. Uncited authority — 1 678 lines of skill carrying two citations.
2. A convention quoted from memory, one of which was not in the document it was
   attributed to.
3. One record's measurements written as a general rule.
4. A synthesised measurement presented as evidence of benefit.
5. Status where an instruction belongs — "nothing here has been tried on a real
   record", a sentence nobody deletes.
6. Length defeating critical reading.
7. A cross-reference that went stale in the session that wrote it.
8. Over-filling a section because a field could be resolved, not because it was
   wanted.

Only the first two had a guard: the `## Outside references` contract test, and a
`CLAUDE.md` rule. Items 4 and 5 were caught by a person reading the output.

## Decision

**Authoring rules live in `.claude/rules/skills.md`, scoped with `paths:` to
`.claude/skills/**`.** They are instructions to the agent, not a description of
the system, which is what separates them from `docs/analyzers.md`. Path scoping
is the point: the rules load when a skill file is touched, instead of depending on
somebody having opened a document. This is the repository's first
`.claude/rules/` file.

The rule file **cites** `CLAUDE.md` and the ADRs rather than restating them. A
long rule file is the failure it exists to prevent.

Three judgements, made here so the rule file does not have to argue them:

- **The middle sections stay free.** Between `## Inputs` and `## Output` the nine
  stage skills use five different shapes. That is the stage's decision taking its
  own form, not drift, and mandating one shape would flatten the differences that
  make each skill readable. Only the five outer headings are required, and
  `## Checkpoint` is among them because a stage skill without one decides
  silently.
- **The 500-line ceiling is a test, not a note.** The figure is the authoring
  guide's own. A note would have deferred `plan-split` indefinitely; the test
  forced the extraction, and the remedy is a supporting file under `references/`,
  not compressed prose.
- **`CLAUDE.md` gains nothing.** It is at 78 lines of a 200-line budget, and skill
  authoring is topic-scoped by definition. A rule that only matters when a skill
  file is open does not belong in every session.

**Four checks become mechanical**, in `tests/contracts/test_skills.py`: the
required headings per kind, the 500-line ceiling, that every relative link out of
a skill resolves, and that a `lint` finding is named by the skill owning the
section it reports on. The last is derived from each finding's own `location`
field, so it is not a second list to keep in step.

**Three failures stay judgement**: whether a citation supports what it is cited
for, whether an anecdote was compressed, and whether a sentence is an instruction
or a status. A test that pretended to check these would be gamed or disabled, and
`.claude/rules/skills.md` says so rather than leaving the gap implicit.

## Consequences

- `plan-split` went from 507 lines to 472; its `## Surface or programme?` reading
  guidance is now `references/surface-or-programme.md`. Shipped skills confirm
  that a supporting file beside `SKILL.md` is reachable, so the remedy works.
- The `lint` mapping was worse than assumed: of 44 finding codes, **20 were named
  by no skill and three by more than one**. Twelve section-scoped ones were added
  to the four skills that own them, and the nine that belong to no stage — the
  source digest, the analysis pairing, the schema version, an engine name — went
  to `plan-album`, which is what assembles the blocks they check.
- The test asserts "the owning skill names it", **not "exactly one skill names
  it"**. `plan-album` summarises findings its stage skills also carry, and a
  finding can genuinely concern two sections. Naming one twice is cheap; a skill
  not knowing about one is not.
- Relative-link integrity passed on all 93 links the day it was written, so it
  fixed nothing. It is a guard for later, and a weak one: it catches a link whose
  target is *gone*, never one whose target moved on — which is the shape failure 7
  actually took. Both instances were found by grepping.
- **Seven prescriptive figures were withdrawn from four skills.** Auditing the 21
  numbers the skills name as uncalibrated split them three ways. Nine already exist
  in code as a `lint` constant or a model default — there the skill's mention is
  the *only* warning a planner gets that the figure is uncalibrated, so deleting it
  would have left the number operating silently. Five are triggers for a checkpoint
  rather than settings, which `plan-album` had already identified as the only kind
  of number an orchestrator should carry. The remaining seven existed in prose
  alone and prescribed a parameter value: `strength` 0.6–0.8 in two skills, a
  raised `max_click_width_ms`, a lossy-transcode ceiling, a tail length, and a
  de-click edge fade. Each was replaced rather than trimmed — by a redirect to the
  dial with a measured readout (`strength` sends you to the threshold, whose effect
  the manifest's repair rate reports), by derivation from another decision (the
  tail now follows the chosen fade-out), or by a criterion plus a requirement that
  `decision.rationale` record the value as chosen and not sourced.
- One of the seven was not uncited but **mis-cited across quantities**: −2.0 as a
  true-peak ceiling is the same figure as Audacity's −2 dB, which is a peak
  *target* in dBFS. The rule file now says a figure does not carry between
  quantities, because that failure looks like a citation and is not one.
- No behaviour changed: nothing outside prose, tests and the skill registry was
  touched.

# 0001 — Planning lives in Coding Agent skills, not in Python

**Status**: accepted

## Context

Turning a raw side into an album needs two very different kinds of work.
Measuring a recording and cutting audio are mechanical: given the same input they
must always produce the same output. Deciding *where* to cut, *how hard* to
declick and *which pressing this is* is judgement, needs external lookups
(Discogs, MusicBrainz), and changes as the operator learns.

Putting both in one Python codebase means the judgement calcifies into
thresholds, and every improvement risks the mechanical half.

## Decision

Three layers, connected only by schema-versioned JSON:

- the **Analyzer** measures and writes `analysis.json`;
- **planning skills** in `.claude/skills/plan-*` decide and write
  `processing_plan.json`;
- the **DSP executor** applies the plan and writes `manifest.json`.

The Python codebase contains no decision logic. If a value is a choice, it appears
in the plan, authored by a skill.

## Consequences

- The plan is a complete audit trail: each section carries a `decision` block
  naming the skill, its reasoning, its confidence and the evidence it used.
- A heuristic can be rewritten by editing one Markdown file, with no release.
- The executor may not import `analyzer` or `config` — needing a measurement or a
  preference at execution time would mean a decision had leaked out of the plan.
  `tests/contracts/test_layer_boundaries.py` enforces this.
- The cost: a plan cannot be produced by `vinyl-process` alone. An agent (or a
  human writing JSON) sits in the middle, and `vinyl-process lint` is the gate that
  keeps what they produce executable.

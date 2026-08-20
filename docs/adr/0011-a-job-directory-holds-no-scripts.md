# 0011 — A job directory holds no scripts

**Status**: accepted

## Context

Planning a record means choosing boundaries, thresholds and levels. The
project's whole shape rests on those choices living in `processing_plan.json`,
where `decision.rationale` records why, and on the Python codebase containing no
decision logic at all ([0001](0001-planning-lives-in-coding-agent-skills.md)).

A one-off Python file in the job directory defeats that without breaking any rule
that is enforced. It is not in `src/`, so the layer-boundary test never sees it;
it produces a valid plan, so `lint` passes; and it looks like tooling rather than
like a decision.

What it cost, once: a script in a job directory hard-coded the inter-track gap
positions **as seconds**, never read `boundaries.candidates`, and shipped a side
with **11 s of run-out groove noise** appended to the last track. Two properties
of the failure matter more than the record it happened on:

- **Nothing caught it.** The plan was valid, the executor was correct, the
  manifest reproduced. The error was in a choice, and the choice had no record.
- **The script was the only account of how the numbers got there.** Reviewing the
  plan showed sample indices with a rationale that did not explain them, and the
  reasoning was in a file nobody was reviewing.

Both are properties of *where the decision lived*, not of that record.

## Decision

**No scripts in the job directory.** A Python file there is the planning layer
written in Python, which is the one thing this project does not do.

The plan is the record of the decisions; `decision.rationale` is where the
reasoning goes. Where a measurement is genuinely needed to make a decision, the
route is the one `docs/architecture.md` names: probe if you must, then promote the
measurement to an analyzer with a ground-truth test and re-derive the decision
from `analysis.json` before the plan ships.

Repository-level tooling is unaffected and lives in `scripts/` — `plot_review.py`,
`clean_job.py`, `discogs_release.py`. The distinction is not "is it Python" but
**does it decide**: those three render, delete and fetch, and none of them chooses
a boundary.

## Consequences

- Positions in a plan must be traceable to `analysis.json` or to a stated
  argument, and "a script computed them" is not one.
- `clean_job.py` deletes from an allow-list and reports anything it does not
  recognise, so a stray file in a job directory surfaces rather than being swept
  away.
- This is a habit, not a mechanism: nothing fails the build if someone writes
  `boundaries.py` next to the recording. That is why it is written down — the same
  reason `docs/architecture.md` names its two planning-layer exceptions explicitly
  rather than stating an absolute it does not enforce.

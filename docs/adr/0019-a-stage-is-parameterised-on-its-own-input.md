# 0019 — A stage is parameterised on its own input

**Status**: accepted

## Context

The executor runs the stages in a fixed order, and that order is part of what a
plan means ([0012](0012-the-executor-has-a-pre-split-phase.md),
[0016](0016-a-pre-split-stage-may-remap-time.md)). So every stage after the first
acts on the *output* of the one before it.

`analysis.json` describes the capture and nothing else. The Analyzer runs once, on
the file that came off the turntable, before any stage has touched it. Put those
two facts together and a parameter read from `analysis.json` for any stage that is
not first was chosen against a signal that stage will never see.

The failure is silent, which is what makes it worth a record. The plan validates.
`lint` passes. `execute` runs and `verify` reproduces it bit for bit. Nothing
anywhere reports that the number was aimed at a defect population an earlier stage
had already removed.

Measured on one transfer while planning it — third rank of this project's evidence
hierarchy, a measurement on a real transfer:

- `plan-decrackle`'s `## Inputs` section read "From `analysis.json`:" while the
  stage runs **third** in the pre-split phase, after `declick`. Its named inputs
  are `clicks.threshold_sweep`, `clicks.width_histogram` and `surface_noise` —
  all measured on the capture. Re-running those analyzers on the *declicked*
  render instead, three tracks came back with click counts of 1, 2 and 0 against
  11, 17 and 11 on the same tracks before repair. A threshold chosen from the
  capture's figures is aimed at events that no longer exist by the time the stage
  runs.
- `normalize` was already immune, and *why* is the instructive part. Its gain is
  not carried in the plan at all: the executor measures the buffers it is about to
  write ([0003](0003-normalization-gain-is-computed-at-execution.md)). That is the
  one stage whose reference cannot go stale, and it is solved by keeping the
  measurement out of the plan rather than by keeping it fresh.
- The size of the error, had that not been so, was measured on the same record.
  Against the correct post-`declick` reference, taking `peaks.peak_db` from
  `analysis.json` would have been wrong by about 7 dB on both sides — that figure
  is the needle drop, which the cuts discard. Taking the peak of the *cut but not
  yet declicked* render would have been wrong by about 1 dB on one side and **by
  nothing at all on the other**, because only one side's loudest music sample was
  a click. That is how this class of mistake survives review: it is invisible on
  half the evidence.

The mechanism to do it correctly already exists and needed no code. `vinyl-process
analyze` takes any audio file, so a review rung can be analysed exactly like a
capture — which is what [plan-prefilter](../../.claude/skills/plan-prefilter/SKILL.md)'s
checkpoint has always told the planner to do (`analyze review/prefilter/<track>
--analyzers spectral`). It was written into one skill's checkpoint and nowhere
stated as a rule, so it read as that stage's quirk.

## Decision

**A stage's parameters are derived from an analyzer run on the audio that stage
will actually receive.** For any stage that is not first in the executor's order,
that means the review rung ending at the previous stage, not the capture.

The review ladder is therefore **load-bearing twice**: it isolates one stage per
comparison for the listener, and it produces the input the next stage's decision
is measured on. That is the reason each rung must carry every stage decided before
it, and the reason a rung may not skip one.

**The citation rule widens to match.** `CLAUDE.md` said a plan may cite only what
`analysis.json` records. It now reads: only what **an analyzer recorded, in a
document kept in the job directory** — the capture's analysis, or a named analysis
of a review rung (`analysis-<stem>-clicks-20.json`, and the like). The point of
the original rule was that a decision may not rest on an ad-hoc reading nobody can
reproduce, and that is untouched: a number measured in a scratch file is still not
evidence. What changes is that the analyzer's output on a *rendered* stage now
counts, because it is reproducible, named and committed beside the plan.

`normalize` stays the exception and stays solved in code. Where a stage reads the
capture despite not being first, its skill must **name the invariance** that makes
that safe rather than leaving it to be assumed — `mono_merge` reads
`channel_correlation`, which the repair stages ahead of it do not meaningfully
move; `split` reads boundary sections that no pre-split stage relocates, time
rescaling included, because positions stay source indices by
[0016](0016-a-pre-split-stage-may-remap-time.md).

## Consequences

- **The decide-order is partly serial, and that is now a stated cost rather than a
  surprise.** A stage cannot be parameterised until every stage ahead of it is
  settled and rendered, which is why `plan-album` stops at a checkpoint per stage
  instead of presenting them together. Deciding `prefilter` late forces the rungs
  above it to be re-rendered and re-measured.
- Job directories accumulate more analysis documents, one per rung that had to be
  measured. They are small, they contain no timestamps and they regenerate from the
  audio, and they are the third-rank evidence this project's hierarchy asks for —
  so they are kept rather than cleaned. `scripts/clean_job.py` already declines to
  touch an analysis.
- **Nothing in `analyzer/` changes.** The Analyzer stays unaware of the pipeline:
  it measures the file it is given. The chaining lives in the planning procedure,
  which is where a decision belongs.
- **Not enforced by anything, and no test can enforce it.** An analysis document
  does not record which stage of which plan it was taken to inform, and inferring
  it would mean the contract test knowing the executor's order *and* the planner's
  intent. This is a habit written down, like the two planning-layer exceptions in
  `docs/architecture.md`.
- **It does not manufacture a measurement where there is none.** `decrackle` has
  no crackle analyzer at all ([0013](0013-crackle-is-a-separate-stage-with-its-own-detector.md)),
  so no audio, capture or render, yields its threshold directly; the repair rate in
  the receipt remains its only readout, after the fact. What this decision fixes
  for that stage is narrower and still worth having: the neighbouring statistics it
  *does* read, and the audio a listener is asked to judge, both come from the
  declicked render instead of the capture.
- A checkpoint that quotes a figure must now say which audio it describes. On the
  transfer above the same quantity — the album's peak — had three different values
  depending on that answer, and two of them were wrong.

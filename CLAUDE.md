# vinyl-process

## Operating principles

- Three layers, never mixed: the **Analyzer** measures, **planning skills**
  (`.claude/skills/plan-*`) decide, the **DSP executor** executes.
- Never add decision logic to Python. If a value is a choice — a threshold, a
  boundary, an engine, a target level — it belongs in `processing_plan.json`,
  authored by a skill. Python may convert a plan value into an engine's units when
  the mapping is deterministic and documented.
- The executor must not import `analyzer` or `config`. Needing a measurement or a
  preference at execution time means a decision leaked out of the plan.
- `analyzer/` and `dsp/` must not import each other; shared maths goes in
  `signal_ops.py`.
- DSP stays deterministic: no randomness (dither takes its seed from the plan), no
  wall clock in audio paths. Same audio + same plan → bit-identical output.
- Analyzers report facts, never advice. "clipping: 2 regions" yes; "re-record at a
  lower gain" no — that is a decision.
- **Measuring while planning is allowed; leaving the measurement in a scratch file
  is not.** Reaching for raw audio inside a `plan-*` skill is a signal that the
  Analyzer has a gap, not a sin — the cut it produces may well be the right one.
  But the reading is a *probe, not evidence*: the moment it changes a decision,
  promote it to an analyzer with a ground-truth test and re-derive the decision
  from `analysis.json` before the plan ships. A plan may only cite what
  `analysis.json` records. Ad-hoc numbers have nothing behind them and have been
  wrong.
- **Best practice means analogue-ripping practice.** Where a decision needs an
  outside convention, research LP digitisation and needledrop sources and cite
  them in the `rationale`. Digital mastering and streaming-delivery conventions do
  not transfer: they assume a track's edges are digital silence, where here they
  are groove noise at the record's own noise floor. Never quote a convention from
  memory — recalled figures have been unfounded, and one circulating as a platform
  spec was not in that platform's document at all.
- **A number in a skill needs a citation or a warning label.** No `plan-*` skill
  may state a threshold, target, amount or duration without either a source in its
  `## Outside references` section or an explicit mark that it is uncalibrated.
  Every skill must carry that section, with at least one URL in it, and
  `tests/contracts/test_skills.py` fails the build otherwise. A specific record's
  measurements are not a calibration: compress them to the magnitude of the failure
  mode and leave the pressing, the track and the exact dB in that album's
  `processing_plan.json`.
- Positions in contracts are integer sample indices, never seconds.

## Working here

- Run `make check` (ruff + mypy strict + pytest) before declaring work done. Tests
  synthesise their audio; never commit audio files.
- After changing a model in `src/vinyl_process/models/`, run `make schemas` and
  `make examples`; a contract test fails on drift. Breaking contract changes bump
  the major `SCHEMA_VERSION`.
- Adding an analyzer, an engine or a stage: follow the recipe in
  `docs/analyzers.md`, `docs/dsp-engines.md` or the extension-point table in
  `docs/architecture.md`. Each has a contract test that fails if the halves drift.
- Mutating a plan in a test goes through `model_validate`, not
  `model_copy(update=...)` — the latter skips validation.
- A decision worth explaining goes in `docs/adr/` as a new record, not as an edit
  to an existing one.

## Commands

- `vinyl-process analyze <wav> -o analysis.json [--analyzers a,b]`
- `vinyl-process lint <plan> --audio <wav> --analysis analysis.json`
- `vinyl-process execute <plan> --audio <wav> -o <dir>`
- `vinyl-process verify <dir>/manifest.json`
- `vinyl-process engines | analyzers | skills | config show`

Architecture: @docs/architecture.md — Contracts: @docs/data-contracts.md

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

# Architecture

## Scope

`vinyl-process` starts from a raw vinyl recording — one continuous audio file per
side or per album, produced by the separate `vinyl-archive` project — and produces
a processed, split, tagged album fit for listening and long-term archival.
Recording is out of scope.

## The three layers

```
┌─────────────────────────────────────────────────────────────┐
│ Analyzer (Python, src/vinyl_process/analyzer)                │
│   measures — silence, RMS, clicks, transients, peaks,        │
│   spectrum, noise floor, clipping, recording info            │
│   output: analysis.json, with confidence scores              │
└──────────────────────────┬──────────────────────────────────┘
                           │  analysis.json
┌──────────────────────────▼──────────────────────────────────┐
│ Planning Skills (Coding Agent skills, .claude/skills/)       │
│   decides — boundaries, algorithms, thresholds, targets,     │
│   engines, tags, file naming                                 │
│   inputs: analysis.json + Discogs/MusicBrainz + preferences  │
│   output: processing_plan.json                               │
└──────────────────────────┬──────────────────────────────────┘
                           │  processing_plan.json
┌──────────────────────────▼──────────────────────────────────┐
│ DSP Executor (Python, src/vinyl_process/dsp + executor.py)   │
│   executes — split, declick, gain, resample, export, tag     │
│   deterministic: same audio + same plan → same bytes         │
│   output: audio files + manifest.json                        │
└─────────────────────────────────────────────────────────────┘
```

### Why the planning layer is not Python

Subjective decisions — where exactly to cut, how aggressive declicking should be,
which pressing this actually is — benefit from contextual reasoning and external
lookups. Encoding them as Python heuristics makes them rigid and hard to evolve.
Instead each decision is a **Coding Agent skill**: a documented, replaceable
procedure. The Python codebase contains **zero decision logic**. If a value is a
choice, it appears in `processing_plan.json`, authored by a skill.

That buys the three properties this project is built around:

- **Reproducibility** — the plan is a complete, auditable record of every
  decision, including *who* decided and *why* (`decision` blocks). Re-running the
  executor reproduces the album bit for bit.
- **Evolvability** — a skill can be rewritten (better split heuristics, a new
  engine preference) without touching measurement or execution code.
- **Testability** — Analyzer and DSP are pure functions of their inputs and are
  tested conventionally; a skill's output is tested by validating the plans it
  produces (`vinyl-process lint`) against golden analyses.

## Layer responsibilities (hard rules)

| Layer | May | Must never |
|---|---|---|
| Analyzer | read audio, measure, attach confidence | decide processing, write plans, modify audio |
| Planning skill | read analysis / metadata / preferences, write plan sections | read or write audio samples, run DSP |
| DSP engine | transform audio exactly as parameterised | choose parameters, read `analysis.json`, use randomness or the wall clock |

These are enforced mechanically, not by convention:
`tests/contracts/test_layer_boundaries.py` assigns every module to a layer and
fails the build on a forbidden import. Notably the executor may not import
`analyzer` or `config`: if it needed a measurement or a preference to proceed,
that would be a decision, and the plan would no longer be complete.

## Package map

```
vinyl_process
├── errors.py       exception hierarchy; every error carries a CLI exit code
├── hashing.py      SHA-256 of files and of canonical JSON (all digests, one rule)
├── log.py          logging setup; library code logs, never prints
├── signal_ops.py   the arithmetic analyzer and DSP share (click detection, RMS,
│                   fades, interpolation). No contracts, no decisions
├── audio.py        AudioBuffer (float64, frames×channels) + I/O + dither
├── models/         the data contracts (pydantic v2), single source of truth
│   ├── common.py      SourceInfo, DocumentRef, SectionMeta, SCHEMA_VERSION
│   ├── analysis.py    AnalysisDocument and one section model per analyzer
│   ├── plan.py        ProcessingPlan and its five sections
│   └── manifest.py    ExecutionManifest — what the executor actually did
├── config.py       [analyzer.*] measurement parameters, [preferences] for skills
├── analyzer/       base.py + registry.py + runner.py, one module per measurement
├── planning/       skills.py (which skill owns which section) and validation.py
│                   (is this plan executable?). No decision logic
├── dsp/            base.py (engine ABC), registry.py, engines/{native,ffmpeg}
├── metadata/       naming.py (plan metadata → filenames), tagger.py (mutagen)
├── executor.py     walks the plan, dispatches to engines, writes manifest.json
└── cli.py          analyze / lint / execute / verify / validate / introspection
```

## Data contracts

All inter-layer data is JSON validated by pydantic models with `extra="forbid"`
and a `schema_version`. JSON Schemas are generated from the models
(`vinyl-process schemas -o schemas/`) and committed under `schemas/`, so
non-Python consumers — the planning skills included — have a formal contract. A
contract test fails if the committed schemas drift from the models.

Contract evolution: additive changes bump the minor version; breaking changes bump
the major version, and consumers refuse a foreign major.

See [data-contracts.md](data-contracts.md); `examples/` holds real documents
produced by the pipeline, regenerated with `scripts/regenerate_examples.py`.

## Determinism

What is guaranteed:

- **`analysis.json` is byte-identical** across runs of the same input, because it
  contains no timestamps. Per-analyzer wall clock is opt-in (`--timings`).
- **Exported audio is bit-identical** across runs of the same plan and source.
  `vinyl-process verify` re-executes and compares digests to prove it.
- Internal processing is float64; conversion to the export bit depth happens
  exactly once, in `save_audio`.
- Dither is the one place randomness enters, so it is seeded from the plan
  (`export.dither_seed`) using numpy's PCG64 stream, whose output is stable
  across numpy versions.
- The plan pins the engine per stage by name. The manifest records the engine
  version, a digest of each stage's parameters, the library and platform
  versions, and the SHA-256 of the source, the plan and every output file.

What is not: two *different* engines are not required to agree bit for bit. The
native engine is the reproducibility baseline (pure numpy/scipy). The ffmpeg
engine is deterministic for a fixed build; its `gain` matches native to double
rounding, its `adeclick` is its own algorithm. See [dsp-engines.md](dsp-engines.md).

## Flow inside the executor

```
validate the plan (engines, ranges, filenames, source digest) — refuse on error
load source ─▶ split      (sample-exact cuts + the fades the plan asked for)
            ─▶ declick    (per track, engine and parameters from the plan)
            ─▶ normalize  (strategy and target from the plan; gain measured
                           post-declick, because repair changes peaks)
            ─▶ resample   (only if the plan asks for a different rate)
            ─▶ export     (container, bit depth, dither, naming from the plan)
            ─▶ metadata   (tags written into the exported files)
            ─▶ manifest.json
```

Nothing is written until validation passes. Any stage can be disabled in the plan
(`"enabled": false`), so a workflow can run only what it needs — re-tagging an
existing rip disables split, declick and normalize.

Ordering note: the pipeline in the project brief lists *metadata* before
*export*. That is exactly what happens conceptually — the metadata **decision** is
made during planning, ahead of everything — while the **write** must follow
encoding, since tags live inside the exported files. Audio processing is finished
before any tag is touched, which is what keeps re-tagging free of re-processing.

## Split as an optimisation problem

The Analyzer emits *candidates* from independent detectors (silence, RMS valleys,
spectral change), each with a method label and a confidence, plus the playable
region (`lead_in_end_sample` … `lead_out_start_sample`, whose trailing edge is the
run-out groove). It never ranks them into a track list.

The Split skill solves the selection problem: given the expected track count and
durations (Discogs), genre conventions and detector confidence, choose the final
boundary set. The executor cuts at the samples it is given.

## Declick in three stages

```
Analyze                     Parameter selection            Repair
clicks.count/rate      →    engine, algorithm,        →    detect with those
amplitude & width           threshold, click width,        parameters and
histograms, density,        strength, preset               interpolate
transient density           (plan-declick skill)           (DSP engine)
```

Detection maths is shared between the Analyzer and the native engine through
`signal_ops.py`, so the statistics a skill reasons about and the damage the engine
repairs are the same events by construction — without the two layers importing
each other.

## Normalization policy

Album-wide gain is the default: one gain value derived from a whole-album
measurement, preserving the relative dynamics between tracks. `album_peak` and
`album_rms` are album-wide; `track_peak` exists in the contract but the
plan-normalize skill is instructed to avoid it except for compilations assembled
from genuinely mismatched sources.

The skill chooses the *strategy and target*; the executor measures after declick
and computes the gain. That split is deliberate — see
[adr/0003-normalization-gain-is-computed-at-execution.md](adr/0003-normalization-gain-is-computed-at-execution.md).

## Configuration

Two halves, crossing different boundaries:

- `[analyzer.*]` — measurement parameters. They change what is measured, so the
  effective values are recorded per section (`meta.params`) and as a whole
  (`config_digest`) in `analysis.json`.
- `[preferences]` — the user's taste (format, target level, declick intent,
  naming). **Read by planning skills only.** They influence the plan, and the plan
  alone drives the executor, so the plan stays the complete record. The layer test
  enforces this: `executor.py` cannot import `config`.

Resolution order: `--config` → `$VINYL_PROCESS_CONFIG` → `./vinyl-process.toml` →
`$XDG_CONFIG_HOME/vinyl-process/config.toml` → built-in defaults.

## Testing strategy

See [testing.md](testing.md). In short: audio is synthesised in-test with known
ground truth (no binary fixtures in the repository), the analyzer is tested for
*accuracy* against that truth, DSP for exactness, the contracts for strictness and
schema currency, the layer boundaries for architectural drift, and the pipeline
end to end for determinism.

## Extension points

| To add… | Touch |
|---|---|
| a measurement | `analyzer/<name>.py` with `@analyzer(...)` + a section model named after it. The runner resolves dependencies and stamps provenance |
| a DSP engine | `dsp/engines/<name>.py` implementing only the capabilities it has, plus a `register_engine` call — or ship it separately and declare a `vinyl_process.dsp_engines` entry point |
| a decision heuristic | the relevant `.claude/skills/plan-*` skill only |
| a pipeline stage | a plan section model, an executor step, and a `plan-<stage>` skill that owns it |

## Known limitations

- **One source file per plan.** A two-sided album is two recordings, two analyses
  and two plans exported into the same directory. A multi-source plan would need a
  `sources[]` array and per-track source references.
- **`mad_interpolate` is a short-gap repairer.** It removes clicks up to a few
  milliseconds and leaves seams around −60 dBFS; wider damage needs a predictive
  (LPC/Janssen) interpolator, which would be a new algorithm id in the same engine.
- **No loudness (LUFS) normalization.** `album_rms` is a plain RMS target; EBU R128
  would be a new `NormalizeMode` plus a loudness analyzer.
- **No de-noise, de-hum, azimuth or speed correction stages.**

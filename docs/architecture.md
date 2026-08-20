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
| Planning skill | read analysis / metadata / preferences, write plan sections | produce album audio, run pipeline DSP, ship a decision resting on an unrecorded measurement |
| DSP engine | transform audio exactly as parameterised | choose parameters, read `analysis.json`, use randomness or the wall clock |

The planning row used to read "never read or write audio samples". That is too
absolute in two places, and stating it absolutely made things worse rather than
safer, so both exceptions are named here instead.

**A skill may measure raw audio, as a probe.** Neither level nor spectrum settles
where a side's music ends, and a skill forbidden to look will cut in the wrong
place — this happened in both directions on one 12" (see the `periodicity`
analyzer). What it must never do is *decide* on an ad-hoc reading and leave it in
a scratch file: the moment such a measurement changes a boundary, it becomes an
analyzer with a ground-truth test, and the plan cites the recorded section
instead. Otherwise the plan's `rationale` quotes numbers no one can reproduce,
the next record needs the same rediscovery, and the reading itself was never
tested — three that felt solid turned out wrong when they were.

**A skill may write a disposable listening copy**, such as the flat-gain
`review/split-loud/`. It carries no manifest, is never fed to a later stage and is
never compared against; it exists so a person can hear a tail. Everything that
reaches `album/` still comes from the executor and from the plan alone.

Neither exception is enforced by anything. They are habits, which is why they are
written down. The rest are enforced mechanically, not by convention:
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
            ─▶ normalize  (strategy, target and ceiling from the plan; gain
                           measured post-declick, because repair changes peaks,
                           then capped against the true peak)
            ─▶ resample   (only if the plan asks for a different rate)
            ─▶ export     (container, bit depth, dither, naming from the plan;
                           records the true peak it wrote, warns if it clipped)
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
clicks.threshold_sweep →    engine, algorithm,        →    detect with those
 (per rung: two rates,      threshold, click width,        parameters and
  onset coincidence,        strength, interpolator         interpolate
  revolution lock)          (plan-declick skill)           (DSP engine)
amplitude & width
histograms, density,
transient density
```

Detection maths is shared between the Analyzer and the native engine through
`signal_ops.py`, so the statistics a skill reasons about and the damage the engine
repairs are the same events by construction — without the two layers importing
each other.

## Normalization policy

Album-wide gain is the default: one gain value derived from a whole-album
measurement, preserving the relative dynamics between tracks. `album_peak`,
`album_gated_rms` and `album_rms` are album-wide; `track_peak` exists in the
contract but the plan-normalize skill is instructed to avoid it except for
compilations assembled from genuinely mismatched sources.

The skill chooses the *strategy and target*; the executor measures after declick
and computes the gain. That split is deliberate — see
[adr/0003-normalization-gain-is-computed-at-execution.md](adr/0003-normalization-gain-is-computed-at-execution.md).

The plan carries a second, independent decision: `peak_ceiling_db`, in dBTP. A
peak mode's `target_db` is its own ceiling, but a level target is not — it says
how loud, not how high — so an RMS mode without a ceiling used to drive the export
straight into `save_audio`'s clamp with nothing in the manifest to show it. When a
ceiling is set the executor caps the gain against the 4x-oversampled peak, which
bounds the sample peak of any later resampling, and warns that the target level
was not reached. Either way it measures the true peak of what it writes into
`applied_true_peak_db` and warns per track when samples had to be clamped, so
clipping is never silent. See
[adr/0007-a-level-target-needs-a-true-peak-ceiling.md](adr/0007-a-level-target-needs-a-true-peak-ceiling.md).

Which measurement a mode uses is part of the mode id, not a parameter:
`album_gated_rms` measures over BS.1770-4's blocks with its two gates and pools
every track's blocks first, so the inter-track gaps stop counting as programme,
while `album_rms` keeps its ungated average for the case where that is genuinely
what someone quoted —
[adr/0008-album-gated-rms-is-a-separate-mode.md](adr/0008-album-gated-rms-is-a-separate-mode.md).

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
  and two plans exported into the same directory — `split.tracks[].index` carries
  the album-wide track number and `metadata.total_tracks` the album-wide count, so
  the numbering comes out right, and each run needs its own `--manifest` name. What
  this does *not* solve is normalization: `album_peak` is computed per plan, so two
  sides whose loudest passages differ get slightly different gains (0.09 dB on the
  record this was tested against, but arbitrarily more in principle). A true
  album-wide gain needs a multi-source plan, or an explicit-gain mode the skill
  fills in from both analyses.
- **The click threshold cannot be defaulted, and nothing automates the choice.**
  `block_ratio` compares a click-width window against its own 40 ms
  neighbourhood, so the statistic is local — but no ratio suits two pressings, and
  on the album this was measured against the two sides wanted different rungs.
  `clicks.threshold_sweep` reports the whole ladder and the engine refuses to run
  without a threshold, so the choice is explicit rather than hidden; it is still a
  judgement, made per record from the two rates, `onset_coincidence` and
  `revolution_lock`, and confirmed by ear. On one pressing every rung read an onset
  coincidence above 2 — the detector was following the beat at every threshold, and
  the answer was to leave repair off. Separating surface from programme more
  reliably than an energy ratio would be a new algorithm id.
- **The playable region is a level threshold, so a quiet passage can end a side
  early.** `lead_out_start_sample` is where the level last crossed the silence
  threshold. On material that drops out by design — dub, electronic — that fires
  at the drop rather than at the run-out: on one tested side it landed 22 s
  before the music actually stopped, and cutting there would have truncated the
  track. `periodicity` is the cross-check, since a run-out groove repeats once per
  revolution while a quiet outro keeps the beat. `lead_in_end_sample` has the
  mirror problem and comes back `null` when no leading silence is found at all.
- **Wide damage is not repaired at all.** Events wider than
  `max_click_width_ms` are rejected as programme material rather than bridged,
  because at that width the detector cannot tell the two apart — so a scratch
  spanning tens of milliseconds survives. The AR fill (Janssen) reconstructs the
  oscillation across the fraction of a millisecond a click leaves, and leaves seams
  around −60 dBFS; which interpolator is best is unestablished, and there is no
  benchmark with clean references to settle it ([dsp-engines.md](dsp-engines.md)).
- **No loudness (LUFS) normalization.** `album_gated_rms` has BS.1770-4's block
  geometry, its two gates and ReplayGain's album pooling, so it measures the
  programme rather than the silence — but no K-weighting, which is what separates
  a level in dBFS from loudness in LUFS. `album_lufs` would be that filter plus
  conformance tests against the EBU Tech 3341 vectors, and is deliberately absent
  until both exist.
- **No subsonic filter and no DC blocking.** Warp rumble at 0.5–8 Hz and a DC
  offset both inflate the peak a peak mode normalizes against, so an affected
  transfer comes out quieter than the music warrants for reasons nobody can hear.
  `spectral.rumble_db` and `recording_info.dc_offset` measure it and
  `plan-normalize` is told to name it in the rationale; nothing removes it. A
  filter would be a new stage, and on the preservation-versus-listening line it
  belongs upstream in `vinyl-archive` at least as much as here.
- **No de-noise, de-hum, azimuth or speed correction stages.**

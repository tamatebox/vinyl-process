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
│   executes — prefilter, declick, decrackle, mono_merge,       │
│              split, gain, resample, export, tag               │
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
│   ├── plan.py        ProcessingPlan: five required sections + prefilter,
│   │                  which is optional and disabled (adr/0012)
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
load source
  pre-split phase — the whole side, one buffer
            ─▶ prefilter (DC blocking and/or the subsonic high-pass; disabled by
                           default, because removing something the transfer
                           captured is a decision)
            ─▶ declick    (engine and parameters from the plan; the whole side, so
                           the detector's context window is never truncated at a
                           track edge and never sees a fade)
            ─▶ decrackle  (the 1-3 sample bed, per-sample rather than collective;
                           after declick, because discrete defects come before
                           continuous ones. Disabled by default)
            ─▶ mono_merge (fold a mono record's two groove walls onto one signal,
                           level-matched. Last, because the walls are repaired
                           independently first. Disabled by default)
  post-split phase — one buffer per track
            ─▶ split      (sample-exact cuts + the fades the plan asked for)
            ─▶ normalize  (strategy, target and ceiling from the plan; gain
                           measured post-declick, because repair changes peaks,
                           then capped against the true peak)
            ─▶ resample   (only if the plan asks for a different rate)
            ─▶ export     (container, bit depth, dither, naming from the plan;
                           records the true peak it wrote, warns if it clipped)
            ─▶ metadata   (tags written into the exported files)
            ─▶ manifest.json
```

The two phases are [adr/0012](adr/0012-the-executor-has-a-pre-split-phase.md).
Practice orders it this way — DC offset, subsonic filter, clicks, and only then
track labels — and it is also the only ordering in which a noise profile taken
from the medium's own unmodulated groove is reachable at all, since `split`
discards the lead-in, the run-out and every gap middle by rule. A stage's
*position* is therefore part of what a plan means, and moving one is a contract
event rather than a refactor.

Nothing is written until validation passes. Any stage can be disabled in the plan
(`"enabled": false`), so a workflow can run only what it needs — re-tagging an
existing rip disables prefilter, split, declick and normalize.

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

`album_lufs` is the fourth album-wide mode and the only one whose target is in
**LUFS** rather than dBFS. It exists because a user asking for −23 or −14 LUFS was
previously told no; it is a broadcast and streaming convention rather than an LP
one, and `plan-normalize` is instructed not to offer it unasked.

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
- `[rip]` — the chain the record was played and digitised through. Provenance
  rather than taste, and a constant rather than a per-record decision, which is
  why it is configuration; read by planning skills only, on the same terms.
  `plan-metadata` composes it into `metadata.comment` and the plan carries the
  finished string, so no rendering rule lives in Python
  ([adr/0009](adr/0009-the-rip-chain-is-configuration-the-comment-is-a-plan-value.md)).
  It is excluded from `config_digest`: renaming a cartridge cannot change a
  measurement.

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
| a pipeline stage | a plan section model, an executor step, a `Capability`, and a `plan-<stage>` skill that owns it. A stage added after 3.2 is **optional with a disabled default**, so the bump stays minor and archived plans stay re-executable ([adr/0012](adr/0012-the-executor-has-a-pre-split-phase.md)). Decide whether it belongs in the pre-split phase (it needs the whole side, or a reference to the medium's own groove) or after the cuts |

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
- **Loudness normalization exists, and what it does not have is a meter.**
  `album_lufs` applies BS.1770's K-weighting, its channel weighting and its −0.691
  offset on top of the gates and album pooling `album_gated_rms` already had, and
  it ships with conformance tests against EBU Tech 3341's cases 1-6 at two sample
  rates — the only measurement here with a correctness oracle outside this
  repository ([adr/0014](adr/0014-album-lufs-ships-with-its-conformance-tests.md)).
  Two limits remain. Tech 3341's cases **7 and 8 are not covered**: they need
  "authentic programme" audio, and this repository commits none. Cases **9 to 14
  are not applicable**: they test momentary and short-term *meters*, and there is
  no meter here — one integrated figure per album. And the coefficients are
  published for 48 kHz only, so they are re-derived per rate; the standard's own
  997 Hz reference reading comes out at −3.0075 at 44.1 kHz and −3.0276 at 96 kHz
  against its stated −3.01 — inside Tech 3341's ±0.1 LU, and not identical.
- **A subsonic filter improves the listening copy; it does not settle where it
  belongs.** `prefilter` now removes DC and high-passes the subsonic band, so warp
  rumble and a DC offset no longer have to inflate the peak a peak mode normalizes
  against. What has not changed is the argument that this belongs upstream in
  `vinyl-archive` at least as much as here: the capture keeps what the plan
  removes, and the stage is reversible per plan
  ([adr/0012](adr/0012-the-executor-has-a-pre-split-phase.md)). It is disabled by
  default for that reason, and `plan-normalize` still names rumble in the
  rationale where it costs gain, because the honest answer on a given record may
  be to leave it in.
- **De-noise is not built, but it is no longer blocked.** A noise profile has to
  come from the medium's own unmodulated groove — the lead-in, the run-out, or an
  inter-track gap — because a profile taken from a quiet *musical* passage models
  the music too. `plan-split` discards all three by rule, on every record, so no
  stage *after* `split` can ever see one; that was the shape of the pipeline, not a
  property of any pressing. The executor now has a pre-split phase, which is where
  such a stage would sit and is the order practice uses (Audacity's LP workflow
  reduces hiss at step 10 and places the track labels at step 11). What remains to
  build: a `denoise` plan section carrying the profile's *region* as source sample
  indices — the executor may not read `analysis.json`, so a skill has to choose the
  region from `silence.regions` and write it into the plan — plus the engine
  capability and the calibration. The measurement side is already there:
  `silence.regions` carries `mean_rms_db` per gap, and `surface_noise` and
  `spectral.bands` cover the whole file.
- **`decrackle` exists, and its reach is bounded by the material.** `block_ratio`
  makes a *collective* decision — it asks whether a short segment is an outlier
  against its neighbourhood — and that is the right question for a discrete
  impulse of a few hundred microseconds. Crackle is a different defect: very
  short events, one to three samples, repeated densely enough to be heard as a
  continuous texture rather than as countable ticks. Each one is a weak outlier
  and there are thousands, so a threshold low enough to catch them starts
  interpolating the music long before it clears the bed. The tool for it is a
  per-sample post-process that examines every sample individually, which is why
  ClickRepair ships DeClick and DeCrackle as separate controls and documents that
  its click detector "is not particularly attuned" to crackle. Lowering
  `declick.threshold` is the wrong lever, and reaching for it is how a day gets
  spent.

  So `decrackle` is a separate stage with a per-sample detector
  ([adr/0013](adr/0013-crackle-is-a-separate-stage-with-its-own-detector.md)).
  What remains a limitation is its **reach**: the statistic divides a sample's
  curvature by the mean curvature of its neighbourhood, and high-frequency
  programme content raises that denominator. Measured on synthesised material, a
  3.1 kHz tone at −22 dBFS carries a curvature comparable to a crackle event 40 dB
  below the programme, and detections across one injected bed fell by more than
  half against the same bed under a bass line. The failure direction is the safe
  one — fewer interpolations exactly where they would be most audible — but two
  things follow: a threshold does not transfer between passages of one side, and a
  bed below the material's own curvature is not reachable at any threshold. That is
  a stopping point rather than a setting yet to be found.
- **No de-noise, and the ffmpeg route was measured rather than assumed.**
  `afftdn` is the obvious delegate and the pre-split phase is now the right place
  for it, but two things blocked shipping it. Its `noise_floor` dominates the
  result — measured on synthesised noise, `nr=9:nf=-40` reduced the bed by 3.6 dB
  while `nr=20:nf=-45` managed 1.2 dB — and **no reference says what to set it
  to**; Audacity's "sensitivity 6.00" is Audacity's own scale, not this one's.
  Worse for the design this project wanted: `afftdn`'s own `sample_noise`
  start/stop commands, driven through `asendcmd`, produced output **identical to
  no command at all** on ffmpeg 9.0.1 across all three command spellings, so the
  plan cannot hand the filter a profile region. The alternative, `band_noise`,
  needs the 15 bands' frequency edges, and the filter documentation does not give
  them. `track_noise` did the most work of anything tested (−6.7 dB, tone
  untouched) and needs no region — but it is the filter deciding, which is the one
  thing a plan is supposed to record. So de-noise is **research first**: the
  missing piece is the reference, not the code.
- **The fades no longer run before `declick`** — this entry is kept because the
  reasoning is why the order changed. `native.split()` applies the fades, and the
  executor's order used to be `split → declick`, so repair saw ramped material. The
  energy ratio is invariant to a constant scale but not to a ramp across its 40 ms
  context window: a fade-in makes the context after the window louder than the
  context before it, which lowers the ratio and biases the detector *towards
  missing* clicks — in the head and tail margins, which are bare surface and
  therefore where a record's clicks are densest. A 250 ms linear fade changes
  amplitude by about 16 % over 40 ms, so roughly 35 % in energy. `declick` now runs
  pre-split on the whole side, so it sees neither the fades nor a truncated context
  window ([adr/0012](adr/0012-the-executor-has-a-pre-split-phase.md)). The
  remaining wrinkle is cosmetic: the plan still cannot express "cut without fades,
  repair, then fade" as a sequence, because the fades are attributes of
  `split.tracks[]` rather than a stage of their own — it no longer matters, since
  nothing runs between the cut and the fade.
- **A mono record's redundancy is used at the merge and nowhere else.**
  `mono_merge` folds the two groove walls, which buys about 3 dB against one wall
  and cancels vertical noise outright
  ([adr/0015](adr/0015-a-mono-record-has-two-observations-of-one-signal.md)). What
  still ignores the redundancy is `declick`: it detects on the channel **mean** and
  repairs every channel over the same span, where the reference makes "decisions on
  click detection and repair in the two channels… independently". On a mono record
  that repairs the clean wall along with the damaged one, which is the opposite of
  what two observations are for. Per-channel detection would change output bytes
  for any plan with declick enabled, so it needs its own decision rather than being
  slipped in.
- **No de-hum, de-clip, azimuth or speed correction stages.** `prefilter`,
  `decrackle` and `mono_merge` are the pre-split stages that exist. `clipping` measures a clipped
  transfer but nothing repairs one: ffmpeg's `adeclip` makes the implementation
  nearly free, which is the trap — no reference was found for how far
  reconstruction may credibly go, and a stage with an uncalibrated skill would get
  enabled and dialled by ear. `plan-album`'s first checkpoint prefers a re-record,
  and that stays the answer until a reference says how much reconstruction is
  defensible.

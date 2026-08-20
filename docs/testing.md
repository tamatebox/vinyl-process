# Testing Strategy

```sh
pytest                  # ~260 tests, a few seconds
pytest --cov            # branch coverage; currently ~95 %
ruff check . && ruff format --check .
mypy                    # strict on src/, relaxed but checked on tests/
```

## Fixtures: synthesised, never committed

`tests/fixtures/synth.py` generates lead-in / tracks / lead-out recordings from a
fixed seed, with configurable gaps, per-track levels and injected clicks, and
returns the ground truth alongside the file. The repository therefore contains no
binary audio, and every expected value is known by construction — which is what
lets the analyzer tests assert *accuracy* rather than merely shape.

The recording and its analysis are session-scoped fixtures; measuring a
20-second stereo file is the slowest thing in the suite.

## What each suite guarantees

### `tests/unit/`

- **`test_signal_ops.py`** — the shared arithmetic: framing, click detection
  (including the two regression cases that mattered: percussive attacks must not be
  detected, and a near-silent noise floor must not defeat detection), repair
  quality, strength scaling, fades, onset detection.
- **`test_audio.py`** — buffer invariants, round-trips through every export target,
  export clipping, and that dither is seeded (same seed → identical bytes,
  different seed → different bytes).
- **`test_analyzers.py`** — every measurement against the fixture's truth: silence
  regions match the generated gaps, lead-in/lead-out are found, every interior gap
  has a silence candidate, every injected click is detected, peaks match the
  synthesised amplitude, channel balance matches the applied imbalance. Also:
  byte-identical analysis across runs, subset selection with dependencies, config
  overrides reaching the analyzer, and graceful degradation when one analyzer fails.
- **`test_analyzer_registry.py`** — dependency ordering, cycle detection, parameter
  typo rejection, typed section access.
- **`test_dsp.py`** — sample-exact splits, exact gain, deterministic declick,
  capability and availability refusals, plug-in discovery (including a broken
  plug-in not breaking the built-ins), and that the ffmpeg and native `gain`
  implementations agree to 1e-12.
- **`test_validation.py`** — one test per finding the linter can report.
- **`test_config.py`**, **`test_naming.py`**, **`test_tagger.py`** — resolution
  order and strictness; filename sanitising and template errors; tags across FLAC,
  WAV and AIFF, artwork, and re-tagging.

### `tests/contracts/`

- **`test_documents.py`** — round-trips, `extra="forbid"` rejection at every
  nesting level, the schema-major gate, and each model validator (contiguous
  non-overlapping tracks, unique tag indices, closed export enums, bounded
  confidence).
- **`test_schemas.py`** — the committed JSON Schemas match the models, and the
  documents in `examples/` still validate. Drift fails the build.
- **`test_analyzer_sections.py`** — analyzers and document sections stay in
  one-to-one correspondence.
- **`test_skills.py`** — every plan section has exactly one owning skill, every
  registered skill exists on disk with valid frontmatter, no undeclared skill is
  installed, and each stage skill actually mentions the section it owns.
- **`test_layer_boundaries.py`** — the architecture itself: every module is
  assigned a layer, every layer declares what it must not import, and a new package
  with no rule fails the suite. This is what makes "the layers never overlap" a
  fact rather than an intention.

### `tests/e2e/`

- **`test_pipeline.py`** — the full run: a tagged album appears, executing twice is
  bit-identical, the manifest records every stage and the environment, album gain
  preserves the 6 dB difference between two tracks while `track_peak` flattens it,
  declick removes everything audible, fades reach the edges, disabled stages are
  recorded as skipped, a mismatched or truncated source is refused before anything
  is written, existing files are protected, other containers and dithered 16-bit
  exports work, resampling is applied and recorded — and a source-level assertion
  that the executor never mentions the analyzer.
- **`test_cli.py`** — every command including its failure exit codes, with
  `verify` catching a tampered manifest.
- **`test_module_entrypoint.py`** — `python -m vinyl_process` works, not only the
  installed console script.

## Skills

Skills are exercised by an agent, not by pytest. Their contract is what is tested
here: `test_skills.py` checks the registry against the files on disk, and
`vinyl-process lint` is the gate a skill must pass before handing a plan over. To
test a skill by hand, run it against a golden `analysis.json` and lint the result.

## Conventions

- `filterwarnings = ["error"]`: a new warning fails the suite.
- Test names state the claim (`test_lead_in_and_lead_out_are_detected`), and
  regression tests say what broke.
- Mutating a plan in a test goes through `model_validate`, never
  `model_copy(update=...)` — the latter skips validation and would exercise a shape
  that can never come off disk.

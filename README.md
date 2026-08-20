# vinyl-process

Turns a raw vinyl recording — produced by the separate `vinyl-archive` project —
into a finished digital album: split into tracks, declicked, normalized, tagged and
exported for listening and long-term archival.

## Architecture in one paragraph

The system is three independent layers connected only by schema-versioned JSON.
The **Analyzer** (Python) measures the recording and writes `analysis.json`; it
never decides anything. **Planning skills** (Coding Agent skills in
`.claude/skills/`) read that analysis plus external metadata (Discogs,
MusicBrainz) and user preferences, and write `processing_plan.json`; they never
touch audio. The **DSP executor** (Python) applies the plan and writes
`manifest.json`; it never makes a subjective choice — and it cannot even read the
analysis. Given identical audio and an identical plan, the output is bit-identical.

```
Raw recording ──▶ Analyzer ──▶ analysis.json
                                   │
     Discogs / MusicBrainz ──▶ Planning skills ──▶ processing_plan.json
                                                        │
                       Raw recording ──▶ DSP executor ──▶ album + manifest.json
```

## Install

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

Python 3.11+. `ffmpeg` on `PATH` is optional and enables the `ffmpeg` engine.

## Quickstart

```sh
# 1. Measure — pure measurement, no decisions
vinyl-process analyze side-a.wav -o analysis.json

# 2. Plan — performed by Coding Agent skills; in Claude Code:
#      /plan-album side-a.wav
#    They read analysis.json + Discogs/MusicBrainz and write processing_plan.json.

# 3. Check the plan is executable before spending any DSP time
vinyl-process lint processing_plan.json --audio side-a.wav --analysis analysis.json

# 4. Execute — deterministic DSP, export, tagging
vinyl-process execute processing_plan.json --audio side-a.wav -o ./album

# 5. Prove it reproduces
vinyl-process verify ./album/manifest.json
```

Introspection: `vinyl-process engines`, `analyzers`, `skills`, `config show`.
Full reference: [docs/cli.md](docs/cli.md).

## Repository layout

```
src/vinyl_process/
  models/        the data contracts (pydantic v2) — single source of truth
  analyzer/      measurement only; one module per measurement, registry-driven
  planning/      which skill owns which plan section, and plan validation
  dsp/           deterministic execution: engine ABC, registry, engines/
  metadata/      filename rendering and tag writing (mutagen)
  audio.py       AudioBuffer (float64) + I/O + the one place dither happens
  signal_ops.py  arithmetic shared by analyzer and DSP (detection, RMS, fades)
  executor.py    runs a plan end to end, writes manifest.json
  cli.py         analyze / lint / execute / verify / validate / introspection
.claude/skills/  the planning layer: plan-album, plan-split, plan-declick,
                 plan-normalize, plan-metadata, plan-export
schemas/         generated JSON Schemas for the contracts (committed)
examples/        real documents produced by the pipeline
docs/            architecture, contracts, CLI, engines, analyzers, testing, ADRs
tests/           unit + contract + end-to-end, on synthesised audio
```

## Design rules

- The Analyzer **measures**, skills **decide**, DSP **executes** — never mixed, and
  `tests/contracts/test_layer_boundaries.py` fails the build if an import crosses a
  line.
- All intermediate data is schema-validated JSON with a `schema_version`, and every
  position is an integer sample index.
- DSP is deterministic: no randomness (dither is seeded from the plan), no
  wall-clock dependence, engines pinned by name per stage, digests of everything in
  the manifest.
- Album-wide normalization by default; per-track normalization is intentionally
  discouraged.
- Nothing is written until the plan validates.

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | The three layers, package map, determinism guarantees, extension points, known limitations |
| [docs/data-contracts.md](docs/data-contracts.md) | `analysis.json`, `processing_plan.json`, `manifest.json` field by field |
| [docs/cli.md](docs/cli.md) | Every command, option and exit code |
| [docs/dsp-engines.md](docs/dsp-engines.md) | The engine contract, the built-ins, how to add one |
| [docs/analyzers.md](docs/analyzers.md) | What is measured and how to add a measurement |
| [docs/testing.md](docs/testing.md) | What each test suite guarantees |
| [docs/adr/](docs/adr/) | Why the awkward parts are the way they are |

## Development

```sh
make check      # ruff + mypy + pytest
make test       # pytest with coverage
make schemas    # regenerate schemas/ after changing a model
make examples   # regenerate examples/ from the pipeline
```

## License

MIT — see [LICENSE](LICENSE).

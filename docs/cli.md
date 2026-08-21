# CLI Reference

```
vinyl-process [-v|-q] [--log-format text|json] [--config FILE] COMMAND
```

Global options apply to every command. Logs go to stderr, so stdout stays a clean
channel for JSON. Exit codes come from the exception hierarchy: `65` bad data,
`66` missing input, `69` engine unavailable, `70` execution failure, `74` audio
I/O, `78` bad configuration.

## The pipeline

### analyze

```sh
vinyl-process analyze recording.wav -o analysis.json
vinyl-process analyze recording.wav -o - --analyzers clicks,transients
```

Measures the recording. `--analyzers` selects a subset by name and pulls in
dependencies automatically (`boundaries` also runs `rms_profile`, `surface_noise`
and `silence`). `-o -` writes to stdout. `--timings` records per-analyzer wall
clock, which breaks byte-for-byte reproducibility of the document, so it is off by
default. A failing analyzer degrades the document and exits 65 unless
`--allow-failures` is given.

### Planning

Planning is not a CLI command — it is performed by the Coding Agent skills in
`.claude/skills`. In Claude Code:

```
/plan-album recording.wav
```

`vinyl-process skills` lists the skills and which plan section each one owns.
`vinyl-process skills --map` adds the executor stage each one drives, the phase it
runs in and the engine capability it needs — the three places where that
correspondence is not one-to-one are printed under the table. `--json` carries the
same fields.

### lint

```sh
vinyl-process lint processing_plan.json --audio recording.wav --analysis analysis.json
vinyl-process lint processing_plan.json --json
vinyl-process lint processing_plan.json --strict     # warnings are failures too
```

Answers "is this plan executable?" — the questions the schema cannot: unknown or
incapable engines, cuts past the end of the recording, fades longer than their
track, a fade at a gapless join, a filename template that fails to render or
collides, a source digest that no longer matches, an analysis of a different
recording, and the level decisions that end in a clipped album — an RMS target
without a `peak_ceiling_db`, a ceiling with no headroom left for inter-sample
peaks, a true peak the gain will push past full scale, and amplifying a source
that is already clipped. Exits 65 if anything is fatal.

### execute

```sh
vinyl-process execute processing_plan.json --audio recording.wav -o ./album
```

Runs the plan and writes the tracks plus `manifest.json`. Nothing is written until
validation passes. Existing files are protected — pass `--overwrite` to replace
them. `--no-verify-source` skips the digest check (the length check still applies,
so truncated audio cannot silently produce short tracks).

It also writes **a copy of the plan beside the receipt** — `manifest.json` gets
`manifest.plan.json`, `manifest-side-a.json` gets `manifest-side-a.plan.json`. The
copy is byte-identical to the plan file, so its SHA-256 is the one the manifest
records. The manifest carries the plan's path and digest, and a digest is one-way:
without the copy, a plan that is later edited or discarded takes the parameters
that ran with it. See
[adr/0018](adr/0018-the-receipt-retains-the-plan-that-produced-it.md).

`--manifest NAME` names the receipt. A two-sided record is two plans exported into
one album directory, and each needs its own:

```sh
vinyl-process execute plan-side-a.json --audio side-a.flac -o album --manifest manifest-side-a.json
vinyl-process execute plan-side-b.json --audio side-b.flac -o album --manifest manifest-side-b.json
```

Side B's plan numbers its tracks 6-10 (`split.tracks[].index`) and sets
`metadata.total_tracks` to 10, so the two runs land in one directory without
colliding and tag as `6/10` rather than `1/5`.

### verify

```sh
vinyl-process verify album/manifest.json
vinyl-process verify album/manifest.json --plan processing_plan.json --audio recording.wav
```

Re-executes the plan into a temporary directory and compares every output digest
with the manifest. Exits 70 and lists the differing files if the album is not
reproducible.

It looks for the plan in this order: `--plan`, then the retained copy beside the
manifest, then the path the manifest records, then that filename beside the
manifest. Whatever it finds, **the plan's digest is checked against
`manifest.plan.sha256` first**, and a mismatch exits 66 saying the plan changed —
because re-running a *different* plan and reporting an output mismatch says the
pipeline stopped reproducing when what really happened is that the plan was not
kept. The recorded audio path is resolved the same way, since both paths are
relative to whatever directory ran `execute`.

A render made before a stage moved will not reproduce, and that is a contract
change rather than a fault: `declick` ran after `split` until
[adr/0012](adr/0012-the-executor-has-a-pre-split-phase.md), so a pre-0012 manifest
with declick enabled differs by design. The stage order in `manifest.stages[]`
tells you which era a receipt is from.

## Contracts and introspection

| Command | Purpose |
|---|---|
| `validate DOC` | Validate any document against its contract (type is read from `document_type`) |
| `schemas -o schemas/` | Regenerate the committed JSON Schemas from the models |
| `engines [--json]` | DSP engines, capabilities, availability, versions |
| `analyzers [--json]` | Analyzers, versions, dependencies, default parameters |
| `skills [--json]` | Planning skills, the section each owns, whether it is installed |

## Configuration

```sh
vinyl-process config init            # write a commented vinyl-process.toml
vinyl-process config path            # which file would be used
vinyl-process config show [--json]   # the effective settings (skills read this)
```

`[analyzer.*]` changes what is measured and is recorded in `analysis.json`;
`[preferences]` is read by planning skills only and never by the executor.

## A complete session

```sh
vinyl-process analyze side-a.wav -o analysis.json
# → /plan-album side-a.wav   (skills write processing_plan.json)
vinyl-process lint processing_plan.json --audio side-a.wav --analysis analysis.json
vinyl-process execute processing_plan.json --audio side-a.wav -o "./Pink Floyd - The Dark Side of the Moon"
vinyl-process verify "./Pink Floyd - The Dark Side of the Moon/manifest.json"
```

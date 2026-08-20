"""Command-line interface.

The CLI exposes the two Python layers and the tooling around the contracts;
planning happens *between* ``analyze`` and ``execute`` and is performed by the
Coding Agent skills in ``.claude/skills`` (``vinyl-process skills`` lists them).

    vinyl-process analyze recording.wav -o analysis.json
    #   ... planning skills write processing_plan.json ...
    vinyl-process lint processing_plan.json --audio recording.wav --analysis analysis.json
    vinyl-process execute processing_plan.json --audio recording.wav -o ./album
    vinyl-process verify ./album/manifest.json
"""

from __future__ import annotations

import functools
import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar, cast

import click
from pydantic import BaseModel, ValidationError

from vinyl_process import __version__
from vinyl_process.config import EXAMPLE_CONFIG, Config, find_config, load_config
from vinyl_process.errors import ContractError, VinylProcessError, WorkspaceError
from vinyl_process.hashing import digest_file
from vinyl_process.log import LogFormat, configure_logging
from vinyl_process.models import DOCUMENT_MODELS, AnalysisDocument, ProcessingPlan
from vinyl_process.models.manifest import ExecutionManifest

F = TypeVar("F", bound=Callable[..., Any])
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"], "max_content_width": 100}


def handle_errors(command: F) -> F:
    """Turn a :class:`VinylProcessError` into a clean message and exit code."""

    @functools.wraps(command)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return command(*args, **kwargs)
        except VinylProcessError as exc:
            click.secho(f"error: {exc}", err=True, fg="red")
            raise SystemExit(exc.exit_code) from exc

    return wrapper  # type: ignore[return-value]


@click.group(context_settings=CONTEXT_SETTINGS)
@click.option("-v", "--verbose", count=True, help="Log more (repeat for debug).")
@click.option("-q", "--quiet", is_flag=True, help="Log errors only.")
@click.option(
    "--log-format", type=click.Choice(["text", "json"]), default="text", show_default=True
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False),
    default=None,
    help="Configuration file (default: search ./vinyl-process.toml then XDG config).",
)
@click.version_option(version=__version__, prog_name="vinyl-process")
@click.pass_context
def main(
    ctx: click.Context, verbose: int, quiet: bool, log_format: str, config_path: str | None
) -> None:
    """Turn a raw vinyl recording into a processed, tagged digital album."""
    configure_logging(verbose, quiet=quiet, fmt=cast(LogFormat, log_format))
    ctx.obj = {"config_path": config_path}


def _config(ctx: click.Context) -> Config:
    return load_config(ctx.obj.get("config_path") if ctx.obj else None)


# --------------------------------------------------------------------------- #
# measure
# --------------------------------------------------------------------------- #
@main.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, allow_dash=True),
    default="analysis.json",
    show_default=True,
    help="Where to write the analysis document ('-' for stdout).",
)
@click.option(
    "--analyzers",
    default=None,
    help="Comma-separated subset to run; dependencies are added automatically.",
)
@click.option(
    "--timings", is_flag=True, help="Record per-analyzer wall clock (breaks byte equality)."
)
@click.option("--allow-failures", is_flag=True, help="Exit 0 even if an analyzer failed.")
@click.pass_context
@handle_errors
def analyze(
    ctx: click.Context,
    input_file: str,
    output: str,
    analyzers: str | None,
    timings: bool,
    allow_failures: bool,
) -> None:
    """Measure INPUT_FILE and write analysis.json (no processing decisions)."""
    from vinyl_process.analyzer import run_analysis

    selection = (
        [name.strip() for name in analyzers.split(",") if name.strip()] if analyzers else None
    )
    document = run_analysis(input_file, analyzers=selection, config=_config(ctx), timings=timings)
    payload = document.model_dump_json(indent=2) + "\n"

    if output == "-":
        click.echo(payload, nl=False)
    else:
        Path(output).write_text(payload, encoding="utf-8")
        click.echo(f"analysis written to {output}")

    for warning in document.warnings:
        click.secho(f"warning: {warning}", err=True, fg="yellow")
    failed = [run.name for run in document.analyzers if run.status == "failed"]
    if failed and not allow_failures:
        raise ContractError(f"analyzer(s) failed: {', '.join(failed)}")


# --------------------------------------------------------------------------- #
# plan tooling
# --------------------------------------------------------------------------- #
@main.command()
@click.argument("plan_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--audio", "audio_file", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option(
    "--analysis", "analysis_file", type=click.Path(exists=True, dir_okay=False), default=None
)
@click.option("--strict", is_flag=True, help="Treat warnings as failures.")
@click.option("--json", "as_json", is_flag=True, help="Emit findings as JSON.")
@handle_errors
def lint(
    plan_file: str, audio_file: str | None, analysis_file: str | None, strict: bool, as_json: bool
) -> None:
    """Check whether PLAN_FILE is executable (engines, ranges, filenames)."""
    from vinyl_process.planning import validate_plan

    plan = _load(plan_file, ProcessingPlan)
    analysis = _load(analysis_file, AnalysisDocument) if analysis_file else None
    findings = validate_plan(
        plan,
        audio_path=audio_file,
        analysis=analysis,
        analysis_digest=digest_file(analysis_file) if analysis_file else None,
    )

    if as_json:
        click.echo(json.dumps([finding.__dict__ for finding in findings], indent=2))
    else:
        for finding in findings:
            colour = {"error": "red", "warning": "yellow", "info": "cyan"}[finding.severity]
            click.secho(str(finding), fg=colour)
        if not findings:
            click.secho("plan is executable; nothing to report", fg="green")

    fatal = [f for f in findings if f.severity == "error" or (strict and f.severity == "warning")]
    if fatal:
        raise SystemExit(65)


# --------------------------------------------------------------------------- #
# execute
# --------------------------------------------------------------------------- #
@main.command()
@click.argument("plan_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--audio",
    "audio_file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Source audio (defaults to the path recorded in the plan).",
)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(file_okay=False),
    required=True,
    help="Directory for exported tracks and manifest.json.",
)
@click.option("--no-verify-source", is_flag=True, help="Skip the plan/audio SHA-256 check.")
@click.option("--overwrite", is_flag=True, help="Replace existing output files.")
@click.option(
    "--manifest",
    "manifest_name",
    default="manifest.json",
    show_default=True,
    help="Receipt filename; give each side of a record its own.",
)
@handle_errors
def execute(
    plan_file: str,
    audio_file: str | None,
    output_dir: str,
    no_verify_source: bool,
    overwrite: bool,
    manifest_name: str,
) -> None:
    """Deterministically execute PLAN_FILE (processing_plan.json)."""
    from vinyl_process.executor import execute_plan

    plan = _load(plan_file, ProcessingPlan)
    manifest = execute_plan(
        plan,
        output_dir,
        source_path=audio_file,
        plan_path=plan_file,
        plan_digest=digest_file(plan_file),
        verify_source=not no_verify_source,
        overwrite=overwrite,
        manifest_name=manifest_name,
    )
    click.echo(f"{len(manifest.outputs)} track(s) exported to {output_dir}")
    if manifest.applied_gain_db is not None:
        click.echo(f"album gain applied: {manifest.applied_gain_db:+.4f} dB")
    for warning in manifest.warnings:
        click.secho(f"warning: {warning}", err=True, fg="yellow")


@main.command()
@click.argument("manifest_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--plan",
    "plan_file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Plan to re-execute (defaults to the path recorded in the manifest).",
)
@click.option("--audio", "audio_file", type=click.Path(exists=True, dir_okay=False), default=None)
@handle_errors
def verify(manifest_file: str, plan_file: str | None, audio_file: str | None) -> None:
    """Re-run a plan and prove the output is bit-identical to MANIFEST_FILE."""
    from vinyl_process.executor import execute_plan

    manifest = _load(manifest_file, ExecutionManifest)
    plan_source = plan_file or manifest.plan.path
    if not plan_source or not Path(plan_source).is_file():
        raise WorkspaceError(
            "cannot find the plan to re-execute; pass --plan explicitly "
            f"(manifest records {manifest.plan.path!r})"
        )
    plan = _load(plan_source, ProcessingPlan)

    with tempfile.TemporaryDirectory(prefix="vinyl-verify-") as tmp:
        replay = execute_plan(
            plan,
            tmp,
            source_path=audio_file or manifest.source.path,
            plan_path=plan_source,
            plan_digest=digest_file(plan_source),
            overwrite=True,
        )

    expected = manifest.output_digests()
    actual = replay.output_digests()
    differences = sorted(
        name for name in set(expected) | set(actual) if expected.get(name) != actual.get(name)
    )
    for name in differences:
        click.secho(
            f"differs: {name} ({expected.get(name, 'missing')[:12]} != "
            f"{actual.get(name, 'missing')[:12]})",
            fg="red",
        )
    if differences:
        raise SystemExit(70)
    click.secho(
        f"reproduced {len(actual)} file(s) bit-identically (run_key {replay.run_key[:12]})",
        fg="green",
    )


# --------------------------------------------------------------------------- #
# contracts and introspection
# --------------------------------------------------------------------------- #
@main.command()
@click.argument("document_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--type",
    "doc_type",
    type=click.Choice([*DOCUMENT_MODELS, "auto"]),
    default="auto",
    show_default=True,
)
@handle_errors
def validate(document_file: str, doc_type: str) -> None:
    """Validate a JSON document against its contract."""
    raw = json.loads(Path(document_file).read_text(encoding="utf-8"))
    declared = raw.get("document_type") if isinstance(raw, dict) else None
    candidates = (
        [doc_type] if doc_type != "auto" else [declared] if declared else list(DOCUMENT_MODELS)
    )

    problems: dict[str, str] = {}
    for name in candidates:
        model = DOCUMENT_MODELS.get(str(name))
        if model is None:
            problems[str(name)] = f"unknown document_type {name!r}"
            continue
        try:
            model.model_validate(raw)
        except ValidationError as exc:
            problems[str(name)] = str(exc)
            continue
        click.secho(f"valid {name} document", fg="green")
        return

    for name, problem in problems.items():
        click.echo(f"--- as {name} ---\n{problem}", err=True)
    raise SystemExit(65)


@main.command()
@click.option("--json", "as_json", is_flag=True)
def engines(as_json: bool) -> None:
    """List DSP engines, their capabilities and availability."""
    from vinyl_process.dsp import list_engines

    items = [
        {
            "name": engine.name,
            "available": engine.is_available(),
            "capabilities": sorted(engine.capabilities()),
            "version": engine.version(),
        }
        for engine in list_engines()
    ]
    if as_json:
        click.echo(json.dumps(items, indent=2))
        return
    for engine in list_engines():
        click.echo(engine.describe())


@main.command()
@click.option("--json", "as_json", is_flag=True)
def analyzers(as_json: bool) -> None:
    """List analyzers, their versions, dependencies and parameters."""
    from vinyl_process.analyzer import all_analyzers

    specs = all_analyzers()
    if as_json:
        click.echo(
            json.dumps(
                [
                    {
                        "name": spec.name,
                        "version": spec.version,
                        "requires": list(spec.requires),
                        "defaults": dict(spec.defaults),
                        "description": spec.description,
                    }
                    for spec in specs
                ],
                indent=2,
            )
        )
        return
    for spec in specs:
        requires = f" requires {', '.join(spec.requires)}" if spec.requires else ""
        click.echo(f"{spec.name:15s} v{spec.version}{requires}\n    {spec.description}")


@main.command()
@click.option("--json", "as_json", is_flag=True)
def skills(as_json: bool) -> None:
    """List the planning skills and the plan sections they own."""
    from vinyl_process.planning.skills import SKILLS, skills_root

    root = skills_root()
    items = [
        {
            "name": skill.name,
            "owns": skill.owns,
            "reads": list(skill.reads),
            "summary": skill.summary,
            "installed": bool(root and (root / skill.name / "SKILL.md").is_file()),
        }
        for skill in SKILLS
    ]
    if as_json:
        click.echo(json.dumps(items, indent=2))
        return
    for item in items:
        mark = "ok " if item["installed"] else "!! "
        owns = item["owns"] or "-"
        click.echo(f"{mark}{item['name']:16s} owns {owns:10s} {item['summary']}")
    if not root:
        click.secho("no .claude/skills directory found from here", err=True, fg="yellow")


@main.command()
@click.option(
    "-o", "--output-dir", type=click.Path(file_okay=False), default="schemas", show_default=True
)
def schemas(output_dir: str) -> None:
    """Regenerate the committed JSON Schemas from the pydantic models."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, model in DOCUMENT_MODELS.items():
        path = out / f"{name}.schema.json"
        schema = model.model_json_schema(mode="serialization")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://vinyl-process.invalid/schemas/{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        click.echo(f"wrote {path}")


@main.group()
def config() -> None:
    """Inspect configuration (analyzer parameters and skill preferences)."""


@config.command("show")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
@handle_errors
def config_show(ctx: click.Context, as_json: bool) -> None:
    """Print the effective configuration (skills read this)."""
    settings = _config(ctx)
    if as_json:
        click.echo(settings.model_dump_json(indent=2))
        return
    click.echo(f"source: {settings.source_path or 'built-in defaults'}")
    click.echo(f"digest: {settings.digest()[:12]}")
    for key, value in settings.preferences.model_dump().items():
        click.echo(f"preferences.{key} = {value!r}")
    for analyzer_name, params in sorted(settings.analyzer.items()):
        click.echo(f"analyzer.{analyzer_name} = {params!r}")


@config.command("path")
@click.pass_context
@handle_errors
def config_path(ctx: click.Context) -> None:
    """Print the configuration file that would be used."""
    found = find_config(ctx.obj.get("config_path") if ctx.obj else None)
    click.echo(str(found) if found else "(none; built-in defaults)")


@config.command("init")
@click.argument("path", type=click.Path(dir_okay=False), default="vinyl-process.toml")
@click.option("--force", is_flag=True, help="Overwrite an existing file.")
@handle_errors
def config_init(path: str, force: bool) -> None:
    """Write a commented example configuration."""
    target = Path(path)
    if target.exists() and not force:
        raise WorkspaceError(f"{target} already exists; pass --force to overwrite")
    target.write_text(EXAMPLE_CONFIG, encoding="utf-8")
    click.echo(f"wrote {target}")


# --------------------------------------------------------------------------- #
ModelT = TypeVar("ModelT", bound=BaseModel)


def _load(path: str, model: type[ModelT]) -> ModelT:
    try:
        return model.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ContractError(f"{path} is not a valid {model.__name__}:\n{exc}") from exc
    except OSError as exc:
        raise WorkspaceError(f"cannot read {path}: {exc}") from exc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

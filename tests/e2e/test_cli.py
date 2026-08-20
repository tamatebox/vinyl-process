"""CLI surface: every command is exercised, including its failure exit codes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.fixtures.synth import SyntheticRecording
from vinyl_process.cli import main
from vinyl_process.models.analysis import AnalysisDocument
from vinyl_process.models.plan import ProcessingPlan


@pytest.fixture
def cli() -> CliRunner:
    return CliRunner()


def invoke(cli: CliRunner, *args: str, expect: int = 0):
    result = cli.invoke(main, list(args))
    assert result.exit_code == expect, (
        f"vinyl-process {' '.join(args)} exited {result.exit_code}\n{result.output}"
    )
    return result


def test_help_and_version(cli: CliRunner) -> None:
    assert "raw vinyl recording" in invoke(cli, "--help").output
    assert "vinyl-process" in invoke(cli, "--version").output


# --------------------------------------------------------------------------- #
def test_analyze_writes_a_valid_document(
    cli: CliRunner, recording: SyntheticRecording, tmp_path: Path
) -> None:
    output = tmp_path / "analysis.json"
    result = invoke(cli, "analyze", str(recording.path), "-o", str(output))
    assert "analysis written" in result.output
    document = AnalysisDocument.model_validate_json(output.read_text())
    assert document.source.num_samples == recording.num_frames


def test_analyze_can_stream_to_stdout_and_take_a_subset(
    cli: CliRunner, recording: SyntheticRecording
) -> None:
    result = invoke(cli, "analyze", str(recording.path), "-o", "-", "--analyzers", "peaks")
    document = AnalysisDocument.model_validate_json(result.output)
    assert document.peaks is not None
    assert document.clicks is None


def test_analyze_reports_an_unknown_analyzer(cli: CliRunner, recording: SyntheticRecording) -> None:
    result = invoke(cli, "analyze", str(recording.path), "--analyzers", "nope", expect=65)
    assert "unknown analyzer" in result.output


def test_analyze_honours_a_configuration_file(
    cli: CliRunner, recording: SyntheticRecording, tmp_path: Path
) -> None:
    config = tmp_path / "vinyl-process.toml"
    config.write_text("[analyzer.rms_profile]\nhop_seconds = 0.25\n", encoding="utf-8")
    output = tmp_path / "analysis.json"
    invoke(
        cli,
        "--config",
        str(config),
        "analyze",
        str(recording.path),
        "-o",
        str(output),
        "--analyzers",
        "rms_profile",
    )
    document = AnalysisDocument.model_validate_json(output.read_text())
    assert document.rms_profile is not None
    assert document.rms_profile.hop_seconds == 0.25


# --------------------------------------------------------------------------- #
def test_lint_accepts_a_good_plan(
    cli: CliRunner, plan_file: Path, recording: SyntheticRecording
) -> None:
    result = invoke(cli, "lint", str(plan_file), "--audio", str(recording.path))
    assert "executable" in result.output


def test_lint_reports_errors_with_a_nonzero_exit(
    cli: CliRunner, plan: ProcessingPlan, tmp_path: Path
) -> None:
    payload = plan.model_dump(mode="json")
    payload["export"]["track_filename_template"] = "same-name"
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")

    result = invoke(cli, "lint", str(broken), expect=65)
    assert "filename-collision" in result.output


def test_lint_emits_json_and_can_fail_on_warnings(
    cli: CliRunner, plan: ProcessingPlan, tmp_path: Path
) -> None:
    payload = plan.model_dump(mode="json")
    payload["metadata"]["album"] = None
    path = tmp_path / "warn.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = invoke(cli, "lint", str(path), "--json")
    findings = json.loads(result.output)
    assert any(finding["code"] == "no-album-title" for finding in findings)
    invoke(cli, "lint", str(path), "--strict", expect=65)


# --------------------------------------------------------------------------- #
def test_execute_then_verify_round_trip(
    cli: CliRunner, plan_file: Path, recording: SyntheticRecording, tmp_path: Path
) -> None:
    album = tmp_path / "album"
    result = invoke(
        cli, "execute", str(plan_file), "--audio", str(recording.path), "-o", str(album)
    )
    assert "2 track(s) exported" in result.output
    assert "album gain applied" in result.output

    manifest = album / "manifest.json"
    verified = invoke(
        cli, "verify", str(manifest), "--plan", str(plan_file), "--audio", str(recording.path)
    )
    assert "bit-identically" in verified.output


def test_execute_refuses_to_overwrite_without_the_flag(
    cli: CliRunner, plan_file: Path, recording: SyntheticRecording, tmp_path: Path
) -> None:
    album = tmp_path / "album"
    args = ["execute", str(plan_file), "--audio", str(recording.path), "-o", str(album)]
    invoke(cli, *args)
    result = invoke(cli, *args, expect=70)
    assert "already exists" in result.output
    invoke(cli, *args, "--overwrite")


def test_verify_detects_tampering(
    cli: CliRunner, plan_file: Path, recording: SyntheticRecording, tmp_path: Path
) -> None:
    album = tmp_path / "album"
    invoke(cli, "execute", str(plan_file), "--audio", str(recording.path), "-o", str(album))

    manifest_path = album / "manifest.json"
    payload = json.loads(manifest_path.read_text())
    payload["outputs"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    result = invoke(
        cli,
        "verify",
        str(manifest_path),
        "--plan",
        str(plan_file),
        "--audio",
        str(recording.path),
        expect=70,
    )
    assert "differs" in result.output


def test_verify_needs_a_findable_plan(
    cli: CliRunner, plan_file: Path, recording: SyntheticRecording, tmp_path: Path
) -> None:
    album = tmp_path / "album"
    invoke(cli, "execute", str(plan_file), "--audio", str(recording.path), "-o", str(album))
    manifest_path = album / "manifest.json"
    payload = json.loads(manifest_path.read_text())
    payload["plan"]["path"] = "gone.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    result = invoke(cli, "verify", str(manifest_path), expect=66)
    assert "cannot find the plan" in result.output


# --------------------------------------------------------------------------- #
def test_validate_recognises_each_document_type(
    cli: CliRunner, plan_file: Path, recording: SyntheticRecording, tmp_path: Path
) -> None:
    analysis_path = tmp_path / "analysis.json"
    invoke(cli, "analyze", str(recording.path), "-o", str(analysis_path), "--analyzers", "peaks")
    assert "valid analysis" in invoke(cli, "validate", str(analysis_path)).output
    assert "valid processing_plan" in invoke(cli, "validate", str(plan_file)).output

    album = tmp_path / "album"
    invoke(cli, "execute", str(plan_file), "--audio", str(recording.path), "-o", str(album))
    assert "valid manifest" in invoke(cli, "validate", str(album / "manifest.json")).output


def test_validate_rejects_a_broken_document(cli: CliRunner, tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"document_type": "analysis", "generated_by": "x"}', encoding="utf-8")
    result = invoke(cli, "validate", str(path), expect=65)
    assert "as analysis" in result.output


def test_validate_reports_an_unknown_document_type(cli: CliRunner, tmp_path: Path) -> None:
    path = tmp_path / "odd.json"
    path.write_text('{"document_type": "mystery"}', encoding="utf-8")
    result = invoke(cli, "validate", str(path), expect=65)
    assert "unknown document_type" in result.output


# --------------------------------------------------------------------------- #
def test_engines_listing(cli: CliRunner) -> None:
    assert "native" in invoke(cli, "engines").output
    payload = json.loads(invoke(cli, "engines", "--json").output)
    native = next(item for item in payload if item["name"] == "native")
    assert set(native["capabilities"]) == {"prefilter", "split", "declick", "gain"}
    assert native["available"] is True


def test_analyzers_listing(cli: CliRunner) -> None:
    assert "rms_profile" in invoke(cli, "analyzers").output
    payload = json.loads(invoke(cli, "analyzers", "--json").output)
    boundaries = next(item for item in payload if item["name"] == "boundaries")
    assert "silence" in boundaries["requires"]
    assert boundaries["defaults"]


def test_skills_listing_finds_the_installed_skills(cli: CliRunner) -> None:
    payload = json.loads(invoke(cli, "skills", "--json").output)
    assert {item["name"] for item in payload} >= {"plan-album", "plan-split", "plan-export"}
    assert all(item["installed"] for item in payload)
    assert invoke(cli, "skills").output.count("owns") >= 5


def test_schemas_are_regenerated_on_demand(cli: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "schemas"
    invoke(cli, "schemas", "-o", str(target))
    assert {path.name for path in target.glob("*.json")} == {
        "analysis.schema.json",
        "processing_plan.schema.json",
        "manifest.schema.json",
    }


def test_config_show_path_and_init(cli: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "vinyl-process.toml"
    invoke(cli, "config", "init", str(target))
    assert target.is_file()
    result = invoke(cli, "config", "init", str(target), expect=66)
    assert "already exists" in result.output
    invoke(cli, "config", "init", str(target), "--force")

    shown = invoke(cli, "--config", str(target), "config", "show").output
    assert "preferences.export_format" in shown
    assert str(target) in invoke(cli, "--config", str(target), "config", "path").output

    payload = json.loads(invoke(cli, "--config", str(target), "config", "show", "--json").output)
    assert payload["preferences"]["declick_intent"] == "balanced"


def test_logging_options_are_accepted(cli: CliRunner, recording: SyntheticRecording) -> None:
    invoke(
        cli,
        "-v",
        "--log-format",
        "json",
        "analyze",
        str(recording.path),
        "-o",
        "-",
        "--analyzers",
        "peaks",
    )
    invoke(cli, "-q", "analyze", str(recording.path), "-o", "-", "--analyzers", "peaks")

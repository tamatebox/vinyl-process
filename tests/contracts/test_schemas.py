"""The committed JSON Schemas are part of the contract, so they must not drift."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vinyl_process.models import DOCUMENT_MODELS

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "schemas"
EXAMPLE_DIR = REPO_ROOT / "examples"


def generated(name: str) -> dict:
    schema = DOCUMENT_MODELS[name].model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://vinyl-process.invalid/schemas/{name}.schema.json"
    return schema


@pytest.mark.parametrize("name", sorted(DOCUMENT_MODELS))
def test_committed_schema_matches_the_model(name: str) -> None:
    path = SCHEMA_DIR / f"{name}.schema.json"
    assert path.is_file(), f"{path} is missing; run 'vinyl-process schemas -o schemas/'"
    committed = json.loads(path.read_text(encoding="utf-8"))
    assert committed == generated(name), (
        f"{path.name} is out of date; run 'vinyl-process schemas -o schemas/'"
    )


@pytest.mark.parametrize("name", sorted(DOCUMENT_MODELS))
def test_schema_declares_its_identity(name: str) -> None:
    schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert schema["$schema"].startswith("https://json-schema.org/")
    assert name in schema["$id"]
    assert "properties" in schema


def test_no_stray_schema_files() -> None:
    committed = {path.stem.removesuffix(".schema") for path in SCHEMA_DIR.glob("*.json")}
    assert committed == set(DOCUMENT_MODELS)


@pytest.mark.parametrize(
    ("filename", "document_type"),
    [
        ("analysis.example.json", "analysis"),
        ("processing_plan.example.json", "processing_plan"),
        ("manifest.example.json", "manifest"),
    ],
)
def test_examples_validate_against_their_model(filename: str, document_type: str) -> None:
    path = EXAMPLE_DIR / filename
    assert path.is_file(), f"{path} is missing"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["document_type"] == document_type
    DOCUMENT_MODELS[document_type].model_validate(raw)

"""Regenerate ``examples/*.json`` from a synthesised recording.

The examples in this repository are real tool output, not hand-written prose, so
they cannot drift from the contracts. Run after changing any model:

    python scripts/regenerate_examples.py

Paths are rewritten to stable names, and digests, timestamps and the environment
block are replaced with placeholders, so the committed files carry no temporary
directory and no machine-specific values. Everything else is real tool output.
``tests/contracts/test_schemas.py`` asserts the result still validates against the
contracts.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from tests.fixtures.synth import write_recording  # noqa: E402

from vinyl_process.analyzer import run_analysis  # noqa: E402
from vinyl_process.executor import execute_plan  # noqa: E402
from vinyl_process.hashing import digest_bytes, digest_file  # noqa: E402
from vinyl_process.models.plan import ProcessingPlan  # noqa: E402

EXAMPLE_DIR = REPO_ROOT / "examples"
STABLE_NAME = "side-a.wav"
PLACEHOLDER_DIGEST = "0" * 64
PLACEHOLDER_TIME = "2026-01-01T00:00:00+00:00"

#: Measurement series are hundreds of numbers long; one per line makes the
#: examples unreadable, so flat numeric arrays are collapsed onto single lines.
_NUMERIC_ARRAY = re.compile(r"\[\s*\n\s*(-?\d[\d.eE+-]*(?:,\s*\n\s*-?\d[\d.eE+-]*)*)\s*\n\s*\]")


def compact_numeric_arrays(text: str) -> str:
    def collapse(match: re.Match[str]) -> str:
        values = [value.strip() for value in match.group(1).split(",")]
        return "[" + ", ".join(values) + "]"

    return _NUMERIC_ARRAY.sub(collapse, text)


def build_plan(recording, analysis, analysis_digest: str) -> ProcessingPlan:
    def samples(seconds: float) -> int:
        return round(seconds * recording.sample_rate)

    return ProcessingPlan.model_validate(
        {
            "created_by": "plan-album",
            "source": analysis.source.model_dump(),
            "analysis": {"path": "analysis.json", "sha256": analysis_digest},
            "split": {
                "engine": "native",
                "decision": {
                    "skill": "plan-split",
                    "rationale": (
                        "Two silence candidates matched the expected two-track side; cuts placed "
                        "inside the gap with short fades to hide the surface-noise step."
                    ),
                    "confidence": 0.92,
                    "inputs": ["analysis.json#boundaries", "discogs:release/1873013"],
                },
                "tracks": [
                    {
                        "index": index + 1,
                        "start_sample": samples(start),
                        "end_sample": samples(end + 0.1),
                        "fade_in_ms": 20.0,
                        "fade_out_ms": 30.0,
                    }
                    for index, (start, end) in enumerate(recording.programme)
                ],
            },
            "declick": {
                "engine": "native",
                "algorithm": "mad_interpolate",
                "threshold": 6.0,
                "max_click_width_ms": 2.0,
                "strength": 1.0,
                "decision": {
                    "skill": "plan-declick",
                    "rationale": (
                        "Moderate click rate, no loud clicks in the histogram and sparse "
                        "transients: default threshold at full strength."
                    ),
                    "confidence": 0.85,
                    "inputs": ["analysis.json#clicks", "analysis.json#transients"],
                },
            },
            "normalize": {
                "engine": "native",
                "mode": "album_peak",
                "target_db": -1.0,
                "decision": {
                    "skill": "plan-normalize",
                    "rationale": (
                        "Album-wide peak normalization keeps the level relationship between the "
                        "sides' tracks; source is unclipped."
                    ),
                    "confidence": 0.95,
                    "inputs": ["analysis.json#peaks", "analysis.json#clipping"],
                },
            },
            "metadata": {
                "album": "Test Pressing",
                "album_artist": "Synthetic Ensemble",
                "artist": "Synthetic Ensemble",
                "year": 1973,
                "genre": "Electronic",
                "styles": ["Drone"],
                "label": "Fixture Records",
                "catalog_number": "FIX-001",
                "discogs_release_id": "1873013",
                "decision": {
                    "skill": "plan-metadata",
                    "rationale": "Illustrative release; identifiers are placeholders.",
                    "inputs": ["discogs:release/1873013"],
                },
                "tracks": [
                    {"index": 1, "title": "First Movement", "position": "A1"},
                    {"index": 2, "title": "Second Movement", "position": "A2"},
                ],
            },
            "export": {
                "format": "flac",
                "bit_depth": 24,
                "track_filename_template": "{index:02d} - {title}",
                "decision": {
                    "skill": "plan-export",
                    "rationale": "FLAC/24 keeps the capture depth for archival.",
                    "inputs": ["vinyl-process.toml#preferences"],
                },
            },
            "notes": (
                "Example plan for the synthesised fixture used by the test suite: a two-track "
                "side with a 2.2 s gap between tracks."
            ),
        }
    )


def stabilise(payload: dict) -> dict:
    """Replace machine-specific values with placeholders."""
    payload["source"]["path"] = STABLE_NAME
    payload["source"]["sha256"] = PLACEHOLDER_DIGEST
    for key in ("analysis", "plan"):
        if isinstance(payload.get(key), dict):
            payload[key]["sha256"] = PLACEHOLDER_DIGEST
    if "run_key" in payload:
        payload["run_key"] = PLACEHOLDER_DIGEST
    for output in payload.get("outputs", []):
        output["path"] = f"album/{Path(output['path']).name}"
        output["sha256"] = PLACEHOLDER_DIGEST
    for stage in payload.get("stages", []):
        if stage.get("engine_version"):
            stage["engine_version"] = "…"
    if "environment" in payload:
        payload["environment"] = dict.fromkeys(
            ("python", "platform", "numpy", "scipy", "soundfile", "libsndfile", "mutagen"), "…"
        )
    for key in ("started_at", "completed_at"):
        if key in payload:
            payload[key] = PLACEHOLDER_TIME
    if "config_digest" in payload:
        payload["config_digest"] = PLACEHOLDER_DIGEST
    return payload


def main() -> int:
    EXAMPLE_DIR.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vinyl-examples-") as tmp:
        workspace = Path(tmp)
        recording = write_recording(workspace / STABLE_NAME)
        analysis = run_analysis(recording.path)
        analysis_payload = analysis.model_dump_json(indent=2) + "\n"
        analysis_digest = digest_bytes(analysis_payload.encode("utf-8"))

        plan = build_plan(recording, analysis, analysis_digest)
        plan_path = workspace / "processing_plan.json"
        plan_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")

        manifest = execute_plan(
            plan,
            workspace / "album",
            source_path=recording.path,
            plan_path="processing_plan.json",
            plan_digest=digest_file(plan_path),
        )

        documents = {
            "analysis.example.json": json.loads(analysis_payload),
            "processing_plan.example.json": json.loads(plan.model_dump_json()),
            "manifest.example.json": json.loads(manifest.model_dump_json()),
        }

    for filename, payload in documents.items():
        payload = stabilise(payload)
        if "outputs" in payload:
            for output in payload["outputs"]:
                output["path"] = f"album/{Path(output['path']).name}"
        if "environment" in payload:
            payload["environment"] = dict.fromkeys(
                ("python", "platform", "numpy", "scipy", "soundfile"), "…"
            )
        rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        (EXAMPLE_DIR / filename).write_text(compact_numeric_arrays(rendered), encoding="utf-8")
        print(f"wrote examples/{filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

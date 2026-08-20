"""Declarative registry of the planning skills.

Planning itself lives in ``.claude/skills/plan-*/SKILL.md`` — it is performed by
a Coding Agent, not by Python. What lives here is only the *contract*: which
skill owns which section of ``processing_plan.json`` and what it is allowed to
read. It is data, never logic.

Keeping it in code (and testing it) is what makes the skill layer verifiable:
``tests/contracts/test_skills.py`` asserts every plan section has exactly one
owning skill and that every registered skill exists on disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["SKILLS", "SkillSpec", "skill_for_section", "skills_root"]


@dataclass(frozen=True)
class SkillSpec:
    name: str
    owns: str | None
    """Plan section this skill authors; ``None`` for the orchestrator."""

    reads: tuple[str, ...]
    summary: str

    @property
    def relative_path(self) -> str:
        return f".claude/skills/{self.name}/SKILL.md"


SKILLS: tuple[SkillSpec, ...] = (
    SkillSpec(
        name="plan-album",
        owns=None,
        reads=("analysis.json", "release metadata", "vinyl-process.toml"),
        summary="Orchestrates the stage skills, assembles and validates the plan.",
    ),
    SkillSpec(
        name="plan-split",
        owns="split",
        reads=("analysis.json#boundaries", "analysis.json#silence", "release tracklist"),
        summary="Chooses final track boundaries from candidates and expected durations.",
    ),
    SkillSpec(
        name="plan-declick",
        owns="declick",
        reads=(
            "analysis.json#clicks",
            "analysis.json#transients",
            "analysis.json#surface_noise",
            "vinyl-process.toml#preferences",
        ),
        summary="Chooses declick engine, algorithm, threshold, width and strength.",
    ),
    SkillSpec(
        name="plan-normalize",
        owns="normalize",
        reads=(
            "analysis.json#peaks",
            "analysis.json#dynamic_range",
            "analysis.json#clipping",
            "analysis.json#spectral",
            "analysis.json#recording_info",
            "vinyl-process.toml#preferences",
        ),
        summary="Chooses the normalization strategy, target level and peak ceiling.",
    ),
    SkillSpec(
        name="plan-metadata",
        owns="metadata",
        reads=("Discogs", "MusicBrainz", "local metadata", "analysis.json#source"),
        summary="Resolves the exact release and its per-track tags.",
    ),
    SkillSpec(
        name="plan-export",
        owns="export",
        reads=("vinyl-process.toml#preferences", "analysis.json#recording_info"),
        summary="Chooses container, bit depth, sample rate, dither and file naming.",
    ),
)


def skill_for_section(section: str) -> SkillSpec | None:
    return next((skill for skill in SKILLS if skill.owns == section), None)


def skills_root(start: Path | None = None) -> Path | None:
    """Locate ``.claude/skills`` by walking up from ``start`` (default: cwd)."""
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        skills = candidate / ".claude" / "skills"
        if skills.is_dir():
            return skills
    return None

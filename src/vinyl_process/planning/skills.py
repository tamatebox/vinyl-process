"""Declarative registry of the planning skills.

Planning itself lives in ``.claude/skills/plan-*/SKILL.md`` — it is performed by
a Coding Agent, not by Python. What lives here is only the *contract*: which
skill owns which section of ``processing_plan.json``, what it is allowed to read,
and which executor stages its decisions drive. It is data, never logic.

Keeping it in code (and testing it) is what makes the skill layer verifiable:
``tests/contracts/test_skills.py`` asserts every plan section has exactly one
owning skill, that every registered skill exists on disk, and that each
:class:`StageBinding` below still matches the phase and capability the executor
actually requires.

The correspondence is not one-to-one in three places, which is the reason it is
written down rather than inferred from names:

- ``normalize`` needs the ``gain`` capability — the only stage whose name and
  capability differ.
- ``resample`` has no plan section of its own; ``export.sample_rate`` drives it,
  so ``plan-export`` drives two stages.
- ``export``, ``metadata`` and ``resample`` need no engine at all: they are
  ``audio.py`` and ``metadata/``, outside the DSP registry.

``vinyl-process skills`` prints the whole map.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from vinyl_process.dsp.base import Capability
from vinyl_process.models.manifest import StageName

__all__ = [
    "SKILLS",
    "SkillSpec",
    "StageBinding",
    "skill_for_section",
    "skill_for_stage",
    "skills_root",
]

Phase = Literal["pre-split", "post-split"]


@dataclass(frozen=True)
class StageBinding:
    """One executor stage a skill's decisions drive."""

    stage: StageName
    phase: Phase
    capability: Capability | None
    """Engine capability the executor requires for this stage; ``None`` when the
    stage runs outside the DSP registry."""


@dataclass(frozen=True)
class SkillSpec:
    name: str
    owns: str | None
    """Plan section this skill authors; ``None`` for the orchestrator."""

    reads: tuple[str, ...]
    summary: str
    drives: tuple[StageBinding, ...] = field(default_factory=tuple)
    """Executor stages this skill's section parameterises, in pipeline order."""

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
        name="plan-prefilter",
        owns="prefilter",
        reads=(
            "analysis.json#spectral",
            "analysis.json#recording_info",
            "analysis.json#peaks",
            "vinyl-process.toml#preferences",
        ),
        summary="Chooses DC blocking and the subsonic cutoff, ahead of the cuts.",
        drives=(StageBinding("prefilter", "pre-split", "prefilter"),),
    ),
    SkillSpec(
        name="plan-split",
        owns="split",
        reads=(
            "analysis.json#boundaries",
            "analysis.json#silence",
            "analysis.json#periodicity",
            "analysis.json#band_profile",
            "analysis.json#rms_profile",
            "analysis.json#source",
            "release tracklist",
        ),
        summary="Chooses final track boundaries from candidates and expected durations.",
        drives=(StageBinding("split", "post-split", "split"),),
    ),
    SkillSpec(
        name="plan-declick",
        owns="declick",
        reads=(
            "analysis.json#clicks",
            "analysis.json#transients",
            "analysis.json#surface_noise",
            "analysis.json#spectral",
            "vinyl-process.toml#preferences",
        ),
        summary="Chooses declick engine, algorithm, threshold, width and strength.",
        drives=(StageBinding("declick", "pre-split", "declick"),),
    ),
    SkillSpec(
        name="plan-decrackle",
        owns="decrackle",
        reads=(
            "analysis.json#clicks",
            "analysis.json#surface_noise",
            "analysis.json#spectral",
            "vinyl-process.toml#preferences",
        ),
        summary="Chooses the crackle threshold, event width and strength.",
        drives=(StageBinding("decrackle", "pre-split", "decrackle"),),
    ),
    SkillSpec(
        name="plan-mono-merge",
        owns="mono_merge",
        reads=(
            "analysis.json#recording_info",
            "analysis.json#source",
            "release metadata",
        ),
        summary="Decides whether to fold a mono record's two groove walls, and how.",
        drives=(StageBinding("mono_merge", "pre-split", "mono_merge"),),
    ),
    SkillSpec(
        name="plan-speed",
        owns="speed",
        reads=(
            "analysis.json#periodicity",
            "analysis.json#source",
            "release metadata",
            "the person who made the transfer",
        ),
        summary="Records the replay speed that was used and the one intended.",
        drives=(StageBinding("speed", "pre-split", "speed"),),
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
        drives=(StageBinding("normalize", "post-split", "gain"),),
    ),
    SkillSpec(
        name="plan-metadata",
        owns="metadata",
        reads=(
            "Discogs",
            "MusicBrainz",
            "local metadata",
            "analysis.json#source",
            "analysis.json#recording_info",
        ),
        summary="Resolves the exact release and its per-track tags.",
        drives=(StageBinding("metadata", "post-split", None),),
    ),
    SkillSpec(
        name="plan-export",
        owns="export",
        reads=(
            "vinyl-process.toml#preferences",
            "analysis.json#recording_info",
            "analysis.json#source",
        ),
        summary="Chooses container, bit depth, sample rate, dither and file naming.",
        drives=(
            # export.sample_rate drives resample; the stage has no section of its own
            StageBinding("resample", "post-split", None),
            StageBinding("export", "post-split", None),
        ),
    ),
)


def skill_for_section(section: str) -> SkillSpec | None:
    return next((skill for skill in SKILLS if skill.owns == section), None)


def skill_for_stage(stage: str) -> SkillSpec | None:
    """Which skill's decisions parameterise ``stage``."""
    return next(
        (skill for skill in SKILLS if any(b.stage == stage for b in skill.drives)),
        None,
    )


def skills_root(start: Path | None = None) -> Path | None:
    """Locate ``.claude/skills`` by walking up from ``start`` (default: cwd)."""
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        skills = candidate / ".claude" / "skills"
        if skills.is_dir():
            return skills
    return None

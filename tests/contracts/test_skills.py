"""The planning skills are a layer, so their contract is tested like any other."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from vinyl_process.models.plan import ProcessingPlan
from vinyl_process.planning.skills import SKILLS, skill_for_section, skills_root

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
PLAN_SECTIONS = ("split", "declick", "normalize", "metadata", "export")


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"{path} has no YAML frontmatter"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def test_every_plan_section_has_exactly_one_owning_skill() -> None:
    for section in PLAN_SECTIONS:
        assert section in ProcessingPlan.model_fields
        owners = [skill for skill in SKILLS if skill.owns == section]
        assert len(owners) == 1, f"{section} is owned by {[o.name for o in owners]}"


def test_skills_own_only_real_plan_sections() -> None:
    for skill in SKILLS:
        if skill.owns is not None:
            assert skill.owns in PLAN_SECTIONS, f"{skill.name} owns unknown section {skill.owns}"


def test_exactly_one_orchestrator() -> None:
    assert [skill.name for skill in SKILLS if skill.owns is None] == ["plan-album"]


@pytest.mark.parametrize("skill", SKILLS, ids=lambda skill: skill.name)
def test_registered_skill_exists_on_disk_with_matching_frontmatter(skill) -> None:
    path = SKILLS_DIR / skill.name / "SKILL.md"
    assert path.is_file(), f"{skill.relative_path} is missing"
    fields = frontmatter(path)
    assert fields.get("name") == skill.name
    assert fields.get("description"), "a skill needs a description so the agent can find it"
    assert len(fields["description"]) <= 400


def test_no_undeclared_skills_on_disk() -> None:
    on_disk = {path.parent.name for path in SKILLS_DIR.glob("*/SKILL.md")}
    assert on_disk == {skill.name for skill in SKILLS}


def test_each_skill_declares_what_it_reads() -> None:
    for skill in SKILLS:
        assert skill.reads, f"{skill.name} declares no inputs"
        assert skill.summary


def test_lookup_helpers() -> None:
    assert skill_for_section("split") is not None
    assert skill_for_section("nonexistent") is None
    assert skills_root(REPO_ROOT) == SKILLS_DIR


def test_stage_skills_document_the_fields_they_own() -> None:
    """A skill that owns a section must mention that section in its instructions."""
    for skill in SKILLS:
        if skill.owns is None:
            continue
        body = (SKILLS_DIR / skill.name / "SKILL.md").read_text(encoding="utf-8")
        assert skill.owns in body, f"{skill.name} never mentions the {skill.owns!r} section"


OUTSIDE_REFERENCES_HEADING = "## Outside references"
URL_PATTERN = re.compile(r"https?://\S+")


@pytest.mark.parametrize("skill", SKILLS, ids=lambda skill: skill.name)
def test_every_skill_cites_outside_practice(skill) -> None:
    """A skill's domain claims must be checkable, so each one carries citations.

    Every ``plan-*`` skill states numbers — how much repair, how loud, what
    order, what a noise print may contain. Those are matters of LP-transfer
    practice, not of this codebase, and a skill that asserts them without a
    source is uncalibrated judgement written with the authority of a rule. The
    orchestrator is held to the same bar: it decides the pipeline order and the
    review-copy hierarchy, which are practice too.
    """
    body = (SKILLS_DIR / skill.name / "SKILL.md").read_text(encoding="utf-8")
    assert OUTSIDE_REFERENCES_HEADING in body, (
        f"{skill.relative_path} has no {OUTSIDE_REFERENCES_HEADING!r} section — "
        "its domain numbers are uncalibrated"
    )
    section = body.split(OUTSIDE_REFERENCES_HEADING, 1)[1].split("\n## ", 1)[0]
    assert URL_PATTERN.search(section), (
        f"{skill.relative_path} has an {OUTSIDE_REFERENCES_HEADING!r} section "
        "with no citable URL in it"
    )

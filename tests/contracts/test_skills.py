"""The planning skills are a layer, so their contract is tested like any other."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from vinyl_process.models.plan import ProcessingPlan
from vinyl_process.planning.skills import SKILLS, skill_for_section, skills_root

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
RULES_DIR = REPO_ROOT / ".claude" / "rules"
PLAN_SECTIONS = (
    "prefilter",
    "split",
    "declick",
    "decrackle",
    "mono_merge",
    "speed",
    "normalize",
    "metadata",
    "export",
)


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


STAGE_HEADINGS = (
    "## Outside references",
    "## Inputs",
    "## Output",
    "## Checkpoint",
    "## Rules",
)
ORCHESTRATOR_HEADINGS = ("## Outside references", "## Rules")


def headings(path: Path) -> list[str]:
    return [
        line.rstrip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]


@pytest.mark.parametrize("skill", SKILLS, ids=lambda skill: skill.name)
def test_a_skill_carries_the_headings_its_kind_requires(skill) -> None:
    """The two kinds of skill have a fixed skeleton; the middle is deliberately free.

    A stage skill hands a decision back to its owner, so ``## Checkpoint`` is
    not optional — a skill without one decides silently. Between ``## Inputs``
    and ``## Output`` the shape is the stage's own: ``## Decision guide``,
    ``## Procedure``, ``## Reading the sweep``, ``## What this detector cannot
    do`` are all in use and all correct for their stage. Nothing here mandates
    one, and adding a sixth needs no change to this test.
    """
    required = ORCHESTRATOR_HEADINGS if skill.owns is None else STAGE_HEADINGS
    present = headings(SKILLS_DIR / skill.name / "SKILL.md")
    missing = [heading for heading in required if heading not in present]
    assert not missing, f"{skill.relative_path} is missing {missing}"


MAX_SKILL_LINES = 500
RELATIVE_LINK = re.compile(r"\]\((?!https?:|mailto:|#)([^)\s]+)\)")


def skill_files() -> list[Path]:
    return sorted(SKILLS_DIR.glob("*/**/*.md"))


@pytest.mark.parametrize("path", skill_files(), ids=lambda path: str(path.relative_to(SKILLS_DIR)))
def test_a_skill_file_stays_under_the_authoring_ceiling(path: Path) -> None:
    """Length defeats critical reading, and a long skill signals a completeness it lacks.

    500 lines is the authoring guideline's own figure. The remedy when a file
    reaches it is to move detailed reference into a supporting file beside
    ``SKILL.md`` and link to it, not to compress the prose that is left.
    """
    lines = len(path.read_text(encoding="utf-8").splitlines())
    assert lines <= MAX_SKILL_LINES, (
        f"{path.relative_to(REPO_ROOT)} is {lines} lines, over the {MAX_SKILL_LINES}-line "
        "ceiling — move detailed reference into a supporting file and link to it"
    )


@pytest.mark.parametrize("path", skill_files(), ids=lambda path: str(path.relative_to(SKILLS_DIR)))
def test_every_relative_link_out_of_a_skill_resolves(path: Path) -> None:
    """A skill's cross-references are its guard against restating an ADR wrongly.

    They only work if they resolve. A skill has claimed a stage did not exist
    after it shipped, and stated an execution order after it changed; both were
    found by grepping rather than by a test. This will not catch a link whose
    *target moved on* — only one whose target is gone — which is worth knowing
    before trusting it too far.
    """
    broken = [
        target
        for target in (
            match.group(1).split("#")[0]
            for match in RELATIVE_LINK.finditer(path.read_text("utf-8"))
        )
        if target and not (path.parent / target).resolve().exists()
    ]
    assert not broken, f"{path.relative_to(REPO_ROOT)} links to missing {broken}"


def rule_files() -> list[Path]:
    return sorted(RULES_DIR.glob("*.md"))


@pytest.mark.parametrize("path", rule_files(), ids=lambda path: str(path.relative_to(RULES_DIR)))
def test_every_relative_link_out_of_a_rule_resolves(path: Path) -> None:
    """A rule cites the skills and ADRs it declines to restate, so its links carry the same weight.

    The skills' own link test covered ``.claude/skills/**`` only, which left every
    cross-reference out of ``.claude/rules/`` unchecked — found when a rule was
    added that links to a stage skill and to an ADR. Same caveat as the skill
    version: this catches a target that is gone, not one that moved on.
    """
    broken = [
        target
        for target in (
            match.group(1).split("#")[0]
            for match in RELATIVE_LINK.finditer(path.read_text("utf-8"))
        )
        if target and not (path.parent / target).resolve().exists()
    ]
    assert not broken, f"{path.relative_to(REPO_ROOT)} links to missing {broken}"


def lint_finding_codes() -> dict[str, set[str]]:
    """Every ``Finding`` code in ``validation.py``, mapped to the plan locations it cites.

    Read out of the source rather than by calling the checks, because a code is
    only ever a literal at a call site. Parsing rather than grepping so that a
    keyword argument, a positional argument and an f-string location all read
    the same.
    """
    import ast

    source = REPO_ROOT / "src" / "vinyl_process" / "planning" / "validation.py"
    positional = ("severity", "code", "message", "location")
    codes: dict[str, set[str]] = {}
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Finding"):
            continue
        arguments: dict[str, ast.expr] = dict(zip(positional, node.args, strict=False))
        arguments.update({kw.arg: kw.value for kw in node.keywords if kw.arg})
        code = arguments.get("code")
        assert isinstance(code, ast.Constant), (
            f"a Finding code is not a literal at line {node.lineno}"
        )
        assert isinstance(code.value, str)
        location = arguments.get("location")
        rendered = ""
        if isinstance(location, ast.Constant):
            rendered = str(location.value)
        elif isinstance(location, ast.JoinedStr):
            rendered = "".join(
                str(part.value) if isinstance(part, ast.Constant) else "{}"
                for part in location.values
            )
        codes.setdefault(code.value, set()).add(rendered)
    assert codes, "found no Finding codes — validation.py's shape changed"
    return codes


def test_lint_finding_codes_were_found() -> None:
    """Guard the guard: the two tests below are vacuous if the parse comes back thin."""
    assert len(lint_finding_codes()) >= 40


@pytest.mark.parametrize("code", sorted(lint_finding_codes()))
def test_every_lint_finding_is_named_by_a_skill(code: str) -> None:
    """A finding nobody was told about is a check the deciding skill cannot act on.

    ``lint`` runs after the plan is assembled, so a finding is feedback to
    whichever skill authored the section — and it reaches that skill only if
    the skill names it. Nothing but this test connects the two halves, and so
    far they have agreed only because one person wrote both.
    """
    bodies = {
        skill.name: (SKILLS_DIR / skill.name / "SKILL.md").read_text(encoding="utf-8")
        for skill in SKILLS
    }
    assert any(code in body for body in bodies.values()), (
        f"lint emits {code!r} and no skill mentions it"
    )


@pytest.mark.parametrize("code", sorted(lint_finding_codes()))
def test_a_section_scoped_finding_is_named_by_the_skill_that_owns_the_section(code: str) -> None:
    """Where a finding cites a plan section, the skill that authors it must know.

    Derived from the finding's own ``location``, so the mapping is not a second
    list to keep in step. Codes whose location is not a plan section — the
    source digest, the analysis pairing, the schema version, an engine name —
    belong to no stage and are held only to the weaker test above; the
    orchestrator names them because it is what assembles those blocks.

    Not "exactly one skill": ``plan-album`` summarises findings that stage
    skills also carry, and a finding can genuinely concern two sections
    (``speed-and-resample`` is filed under ``export.sample_rate`` and is
    ``plan-speed``'s decision as much as ``plan-export``'s). Naming a finding
    twice is cheap; a skill not knowing about one is not.
    """
    owners = set()
    for location in lint_finding_codes()[code]:
        section = location.split(".")[0].split("[")[0]
        if section in PLAN_SECTIONS:
            owner = skill_for_section(section)
            assert owner is not None
            owners.add(owner.name)
    if not owners:
        pytest.skip(f"{code} is not scoped to a plan section")
    for name in sorted(owners):
        body = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
        assert code in body, f"{name} owns the section {code!r} reports on and never names it"


PRE_SPLIT_STAGES = frozenset({"prefilter", "declick", "decrackle", "mono_merge", "speed"})


def executor_stage_capabilities() -> dict[str, set[str]]:
    """Every ``self._engine(..., "<capability>")`` call, keyed by the method it sits in.

    The executor is the authority on which capability a stage needs. Read out of
    the source so that the registry's :class:`StageBinding` cannot drift from it
    without this failing — the correspondence is not inferable from names
    (``normalize`` requires ``gain``).
    """
    import ast

    source = REPO_ROOT / "src" / "vinyl_process" / "executor.py"
    found: dict[str, set[str]] = {}
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.FunctionDef):
            continue
        for call in ast.walk(node):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
                continue
            if call.func.attr != "_engine" or len(call.args) < 2:
                continue
            if isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str):
                found.setdefault(node.name.lstrip("_"), set()).add(call.args[1].value)
    assert found, "found no _engine calls — executor.py's shape changed"
    return found


def test_every_executor_stage_is_driven_by_exactly_one_skill() -> None:
    """A stage nobody owns is a parameter nobody decided.

    ``resample`` is the case worth the test: it has no plan section of its own,
    so nothing in the plan's shape says who chose it. ``export.sample_rate``
    does, which makes it ``plan-export``'s.
    """
    import typing

    from vinyl_process.models.manifest import StageName

    for stage in typing.get_args(StageName):
        owners = [skill.name for skill in SKILLS if any(b.stage == stage for b in skill.drives)]
        assert len(owners) == 1, f"stage {stage} is driven by {owners}"


def test_a_binding_names_the_capability_the_executor_actually_requires() -> None:
    """The registry's map of stage to capability must match the dispatch that runs."""
    required = executor_stage_capabilities()
    for skill in SKILLS:
        for binding in skill.drives:
            actual = required.get(binding.stage, set())
            if binding.capability is None:
                assert not actual, (
                    f"{skill.name} says {binding.stage} needs no engine, "
                    f"but the executor requires {sorted(actual)}"
                )
            else:
                assert actual == {binding.capability}, (
                    f"{skill.name} says {binding.stage} needs {binding.capability!r}, "
                    f"but the executor requires {sorted(actual)}"
                )


def test_a_binding_names_the_phase_the_stage_runs_in() -> None:
    """Phase is part of what a plan means, so a stage moving is a contract event."""
    for skill in SKILLS:
        for binding in skill.drives:
            expected = "pre-split" if binding.stage in PRE_SPLIT_STAGES else "post-split"
            assert binding.phase == expected, (
                f"{skill.name} puts {binding.stage} in {binding.phase}, expected {expected}"
            )


def test_a_declared_capability_is_implemented_by_some_engine() -> None:
    """A binding that no engine can honour would make the stage unreachable."""
    from vinyl_process.dsp.registry import list_engines

    implemented = {cap for engine in list_engines() for cap in engine.capabilities()}
    for skill in SKILLS:
        for binding in skill.drives:
            if binding.capability is not None:
                assert binding.capability in implemented, (
                    f"{skill.name} needs {binding.capability}, which no engine implements"
                )


def test_the_orchestrator_drives_no_stage() -> None:
    """plan-album decides the order and the gates, never a stage's parameters."""
    for skill in SKILLS:
        if skill.owns is None:
            assert skill.drives == ()

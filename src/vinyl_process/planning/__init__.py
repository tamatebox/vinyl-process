"""Planning support.

The planning *decisions* are made by Coding Agent skills in ``.claude/skills``;
this package holds only their contract (:mod:`vinyl_process.planning.skills`) and
the executability checks a plan must pass
(:mod:`vinyl_process.planning.validation`). No decision logic lives here.
"""

from vinyl_process.planning.skills import SKILLS, SkillSpec, skill_for_section
from vinyl_process.planning.validation import Finding, errors, raise_for_errors, validate_plan

__all__ = [
    "SKILLS",
    "Finding",
    "SkillSpec",
    "errors",
    "raise_for_errors",
    "skill_for_section",
    "validate_plan",
]

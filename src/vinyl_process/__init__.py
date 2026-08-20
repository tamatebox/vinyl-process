"""vinyl-process: turn a raw vinyl recording into a finished digital album.

The package is split into three layers that only ever communicate through
schema-versioned JSON documents:

``analyzer``
    Measures a recording and emits ``analysis.json``. Never decides anything.
``planning``
    Contracts and tooling for the planning layer. The *decisions* themselves are
    made by Coding Agent skills in ``.claude/skills`` which emit
    ``processing_plan.json``. This package holds no decision logic.
``dsp`` / :mod:`vinyl_process.executor`
    Deterministically executes a plan. Never makes a subjective choice.

See ``docs/architecture.md`` for the full design.
"""

from __future__ import annotations

__all__ = ["TOOL_NAME", "__version__"]

TOOL_NAME = "vinyl-process"


def _detect_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("vinyl-process")
    except PackageNotFoundError:  # running from a source tree without install
        return "0.0.0+unknown"


__version__: str = _detect_version()

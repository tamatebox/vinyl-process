"""The three layers must not overlap. This test is the enforcement.

The architecture's central promise — the Analyzer measures, skills decide, DSP
executes — is only real if the code cannot quietly grow a shortcut. Every module
is assigned a layer and every layer declares what it may not import. A new
package must add itself here, or the last test fails.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "vinyl_process"
PACKAGE = "vinyl_process"

#: layer -> layers it must never import.
FORBIDDEN: dict[str, frozenset[str]] = {
    # Leaves: no internal dependencies at all.
    "errors": frozenset({"*"}),
    "hashing": frozenset({"*"}),
    "log": frozenset({"*"}),
    "signal_ops": frozenset({"*"}),
    # Contracts may only rest on leaves (errors, hashing).
    "models": frozenset(
        {"analyzer", "audio", "cli", "config", "dsp", "executor", "log", "metadata", "planning"}
    ),
    "audio": frozenset({"analyzer", "cli", "config", "dsp", "executor", "metadata", "planning"}),
    "config": frozenset({"analyzer", "audio", "cli", "dsp", "executor", "metadata", "planning"}),
    # The measurement layer never reaches into execution.
    "analyzer": frozenset({"cli", "dsp", "executor", "metadata", "planning"}),
    # Engines are parameterised by the plan alone: no analysis, no user config.
    "dsp": frozenset({"analyzer", "cli", "config", "executor", "planning"}),
    "metadata": frozenset({"analyzer", "cli", "config", "dsp", "executor"}),
    # Planning support may introspect engines (capability checks) but never runs them.
    "planning": frozenset({"analyzer", "cli", "config", "executor"}),
    # The executor consults the plan only — preferences must not reach it.
    "executor": frozenset({"analyzer", "cli", "config"}),
    "cli": frozenset(),
    "__init__": frozenset({"*"}),
    "__main__": frozenset(
        {"analyzer", "audio", "dsp", "executor", "metadata", "models", "planning"}
    ),
}


def layer_of(module: str) -> str:
    """``vinyl_process.dsp.engines.native`` -> ``dsp``; the root package -> ``""``."""
    if module == PACKAGE:
        return ""
    return module.removeprefix(f"{PACKAGE}.").split(".")[0]


def modules() -> list[Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def internal_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith(PACKAGE))
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative imports are not used in this package
                raise AssertionError(f"{path}: relative import found; use absolute imports")
            if node.module and node.module.startswith(PACKAGE):
                found.add(node.module)
    return found


@pytest.mark.parametrize("path", modules(), ids=lambda path: str(path.relative_to(PACKAGE_ROOT)))
def test_module_respects_its_layer(path: Path) -> None:
    own_layer = layer_of(
        f"{PACKAGE}.{path.relative_to(PACKAGE_ROOT).with_suffix('')}".replace("/", ".")
    )
    forbidden = FORBIDDEN.get(own_layer)
    assert forbidden is not None, f"layer {own_layer!r} has no rule; add one to FORBIDDEN"

    for imported in internal_imports(path):
        target = layer_of(imported)
        if target in {"", own_layer}:
            continue  # the root package (version only) and same-layer imports are fine
        assert "*" not in forbidden, (
            f"{path.relative_to(PACKAGE_ROOT)} is a leaf module but imports {imported}"
        )
        assert target not in forbidden, (
            f"{path.relative_to(PACKAGE_ROOT)} imports {imported}: "
            f"layer {own_layer!r} must not depend on {target!r}"
        )


def test_every_layer_has_a_rule() -> None:
    layers = {
        layer_of(f"{PACKAGE}.{path.relative_to(PACKAGE_ROOT).with_suffix('')}".replace("/", "."))
        for path in modules()
    }
    assert layers <= set(FORBIDDEN), f"undeclared layer(s): {sorted(layers - set(FORBIDDEN))}"


def test_the_analyzer_and_dsp_layers_share_only_the_arithmetic() -> None:
    """Shared measurement/repair maths belongs in signal_ops, nowhere else."""
    analyzer_imports = set()
    for path in (PACKAGE_ROOT / "analyzer").rglob("*.py"):
        analyzer_imports |= internal_imports(path)
    dsp_imports = set()
    for path in (PACKAGE_ROOT / "dsp").rglob("*.py"):
        dsp_imports |= internal_imports(path)

    shared = {
        module
        for module in analyzer_imports & dsp_imports
        if layer_of(module) not in {"models", ""}
    }
    assert shared <= {
        f"{PACKAGE}.audio",
        f"{PACKAGE}.errors",
        f"{PACKAGE}.log",
        f"{PACKAGE}.signal_ops",
    }

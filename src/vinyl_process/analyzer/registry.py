"""Analyzer registry.

The registry owns *what* can be measured and in what order; the runner owns the
mechanics of running it. Selection resolves dependencies automatically, so
``analyze --analyzers boundaries`` also runs the RMS profile, noise floor and
silence detection it is built on.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from vinyl_process.analyzer.base import AnalyzerFn, AnalyzerSpec
from vinyl_process.errors import AnalysisError

__all__ = ["all_analyzers", "analyzer", "get_analyzer", "resolve_order"]

_ANALYZERS: dict[str, AnalyzerSpec] = {}
_BUILTINS_LOADED = False


def analyzer(
    *,
    name: str,
    version: str,
    description: str = "",
    requires: Iterable[str] = (),
    defaults: Mapping[str, Any] | None = None,
) -> Callable[[AnalyzerFn], AnalyzerFn]:
    """Decorator registering a measurement function."""

    def decorate(fn: AnalyzerFn) -> AnalyzerFn:
        if name in _ANALYZERS:
            raise AnalysisError(f"analyzer {name!r} is already registered")
        _ANALYZERS[name] = AnalyzerSpec(
            name=name,
            version=version,
            description=description or (fn.__doc__ or "").strip().splitlines()[0],
            requires=tuple(requires),
            defaults=dict(defaults or {}),
            fn=fn,
        )
        return fn

    return decorate


def _ensure_builtins() -> None:
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    _BUILTINS_LOADED = True
    # Imported for their registration side effects; lazy so that importing the
    # registry itself stays cheap and cycle-free.
    from vinyl_process.analyzer import (  # noqa: F401
        bands,
        boundaries,
        clicks,
        levels,
        noise,
        periodicity,
        recording,
        rms,
        run_out,
        silence,
        spectral,
        transients,
    )


def get_analyzer(name: str) -> AnalyzerSpec:
    _ensure_builtins()
    try:
        return _ANALYZERS[name]
    except KeyError:
        raise AnalysisError(
            f"unknown analyzer {name!r}; available: {', '.join(sorted(_ANALYZERS))}"
        ) from None


def all_analyzers() -> list[AnalyzerSpec]:
    _ensure_builtins()
    return [_ANALYZERS[name] for name in sorted(_ANALYZERS)]


def resolve_order(selection: Iterable[str] | None = None) -> list[AnalyzerSpec]:
    """Dependency closure of ``selection``, ordered so requirements come first.

    ``None`` selects every registered analyzer. Raises :class:`AnalysisError` on
    an unknown name or a dependency cycle.
    """
    _ensure_builtins()
    wanted = sorted(_ANALYZERS) if selection is None else list(selection)
    for name in wanted:
        get_analyzer(name)

    ordered: list[AnalyzerSpec] = []
    done: set[str] = set()
    visiting: list[str] = []

    def visit(name: str) -> None:
        if name in done:
            return
        if name in visiting:
            cycle = " -> ".join([*visiting, name])
            raise AnalysisError(f"analyzer dependency cycle: {cycle}")
        visiting.append(name)
        spec = get_analyzer(name)
        for dependency in spec.requires:
            visit(dependency)
        visiting.pop()
        done.add(name)
        ordered.append(spec)

    for name in wanted:
        visit(name)
    return ordered

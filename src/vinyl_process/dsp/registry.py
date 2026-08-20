"""Engine registry.

The plan selects an engine *by name* per stage; the executor resolves it here.
Adding an engine is one module plus one :func:`register_engine` call — or, for
engines shipped in a separate distribution, a ``vinyl_process.dsp_engines``
entry point, which is how a third-party engine becomes interchangeable with the
built-ins without touching this repository.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from vinyl_process.dsp.base import DspEngine
from vinyl_process.errors import EngineNotFoundError
from vinyl_process.log import get_logger

ENTRY_POINT_GROUP = "vinyl_process.dsp_engines"
logger = get_logger(__name__)

_ENGINES: dict[str, DspEngine] = {}
_LOADED = False


def register_engine(engine: DspEngine, *, replace: bool = False) -> None:
    """Register ``engine`` under its ``name``.

    ``replace=True`` is for tests and for deliberately shadowing a built-in.
    """
    if engine.name in _ENGINES and not replace:
        raise EngineNotFoundError(f"engine {engine.name!r} is already registered")
    _ENGINES[engine.name] = engine


def get_engine(name: str) -> DspEngine:
    _load()
    try:
        return _ENGINES[name]
    except KeyError:
        available = ", ".join(sorted(_ENGINES)) or "none"
        raise EngineNotFoundError(f"unknown DSP engine {name!r}; available: {available}") from None


def list_engines() -> list[DspEngine]:
    _load()
    return [_ENGINES[name] for name in sorted(_ENGINES)]


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    from vinyl_process.dsp.engines.ffmpeg_engine import FfmpegEngine
    from vinyl_process.dsp.engines.native import NativeEngine

    for engine in (NativeEngine(), FfmpegEngine()):
        _ENGINES.setdefault(engine.name, engine)

    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        try:
            factory = entry_point.load()
            engine = factory()
        except Exception:  # a broken plug-in must not break the built-ins
            logger.exception("failed to load DSP engine plug-in %r", entry_point.name)
            continue
        if not isinstance(engine, DspEngine):
            logger.error(
                "plug-in %r produced %r, which is not a DspEngine", entry_point.name, engine
            )
            continue
        _ENGINES[engine.name] = engine

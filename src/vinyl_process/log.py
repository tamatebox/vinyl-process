"""Logging setup.

The CLI is the only caller: it configures a single handler on the package
logger. Library code never configures logging and never prints — it logs.
"""

from __future__ import annotations

import logging
import sys
from typing import Literal

__all__ = ["configure_logging", "get_logger"]

_ROOT = "vinyl_process"
LogFormat = Literal["text", "json"]


def get_logger(name: str) -> logging.Logger:
    """Return the logger for a module inside the package."""
    if name == _ROOT or name.startswith(f"{_ROOT}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT}.{name}")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        import json

        payload = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def configure_logging(verbosity: int = 0, *, quiet: bool = False, fmt: LogFormat = "text") -> None:
    """Attach one stderr handler to the package logger.

    ``verbosity`` 0 -> WARNING, 1 -> INFO, 2+ -> DEBUG. ``quiet`` forces ERROR.
    Logs go to stderr so that stdout stays a clean channel for JSON output.
    """
    if quiet:
        level = logging.ERROR
    else:
        level = {0: logging.WARNING, 1: logging.INFO}.get(verbosity, logging.DEBUG)

    logger = logging.getLogger(_ROOT)
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(level)
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
    logger.addHandler(handler)

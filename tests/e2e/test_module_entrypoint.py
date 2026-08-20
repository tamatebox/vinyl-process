"""``python -m vinyl_process`` must work, not just the installed console script."""

from __future__ import annotations

import subprocess
import sys


def test_module_invocation_prints_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "vinyl_process", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "raw vinyl recording" in result.stdout

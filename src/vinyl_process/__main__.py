"""Allow ``python -m vinyl_process``."""

from __future__ import annotations

from vinyl_process.cli import main

if __name__ == "__main__":  # pragma: no cover - trivial delegation
    main()

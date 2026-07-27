"""PyInstaller entrypoint for the desktop application."""
from __future__ import annotations

import os

from guandan.gui.app import main


def verify_packaged_ai() -> None:
    """Exercise imports that PyInstaller cannot discover from dynamic paths."""
    from guandan.ai import DIFFICULTY_NAMES, make_strategy

    for difficulty in DIFFICULTY_NAMES:
        strategy = make_strategy(difficulty)
        if strategy.difficulty != difficulty:
            raise RuntimeError(f"AI difficulty mismatch: expected {difficulty}")


if __name__ == "__main__":
    if os.environ.get("GUANDAN_PACKAGE_SMOKE") == "1":
        verify_packaged_ai()
        raise SystemExit(0)
    raise SystemExit(main())

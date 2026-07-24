"""PyInstaller entrypoint for the desktop application."""
from __future__ import annotations

from guandan.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())

"""TUI layout sizing helpers."""
from __future__ import annotations

import os
import shutil
import sys
from typing import Mapping, TextIO

RECOMMENDED_COLUMNS = 140
RECOMMENDED_LINES = 48
MIN_COLUMNS = 118
MIN_LINES = 40

_DISABLE_VALUES = {"1", "true", "yes", "on"}


def terminal_resize_disabled(env: Mapping[str, str] | None = None) -> bool:
    """Return whether automatic terminal resizing should be skipped."""
    values = os.environ if env is None else env
    return values.get("GUANDAN_TUI_NO_RESIZE", "").lower() in _DISABLE_VALUES


def should_request_terminal_resize(
    columns: int,
    lines: int,
    *,
    env: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
) -> bool:
    """Return whether startup should ask the terminal emulator for more space."""
    values = os.environ if env is None else env
    if terminal_resize_disabled(values):
        return False
    if values.get("CI") or values.get("TMUX") or values.get("STY") or values.get("SSH_TTY"):
        return False
    if values.get("TERM", "").lower() == "dumb":
        return False
    if stream is not None and not stream.isatty():
        return False
    return columns < RECOMMENDED_COLUMNS or lines < RECOMMENDED_LINES


def request_terminal_resize(
    *,
    env: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
) -> bool:
    """Request an xterm-compatible terminal window size for the game table."""
    target = stream if stream is not None else sys.stdout
    size = shutil.get_terminal_size(fallback=(0, 0))
    if not should_request_terminal_resize(
        size.columns,
        size.lines,
        env=env,
        stream=target,
    ):
        return False

    target.write(f"\x1b[8;{RECOMMENDED_LINES};{RECOMMENDED_COLUMNS}t")
    target.flush()
    return True


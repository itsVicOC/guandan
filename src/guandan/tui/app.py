"""TUI App 主入口。"""
from __future__ import annotations

from contextlib import suppress

from textual.app import App

from ..storage import history_exists, reconcile_settlements
from .layout import request_terminal_resize
from .screens.main_menu import MainMenuScreen


class GuandanApp(App):
    """掼蛋 TUI App。"""

    TITLE = "掼蛋"
    SUB_TITLE = "v0.8.1-beta.2 · Public Beta"

    def on_mount(self) -> None:
        # Finish any settlement a previous run could not complete, so history
        # and statistics cannot stay permanently divergent after a crash.
        with suppress(OSError, ValueError):
            reconcile_settlements(history_has_game=history_exists)
        self.push_screen(MainMenuScreen())


def run() -> int:
    """启动 TUI。"""
    request_terminal_resize()
    app = GuandanApp()
    return app.run() or 0


if __name__ == "__main__":
    import sys

    sys.exit(run())

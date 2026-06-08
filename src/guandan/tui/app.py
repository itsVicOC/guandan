"""TUI App 主入口。"""
from __future__ import annotations

from textual.app import App

from .screens.main_menu import MainMenuScreen


class GuandanApp(App):
    """掼蛋 TUI App。"""

    TITLE = "掼蛋"
    SUB_TITLE = "v0.6.1 · M6 tuning"

    def on_mount(self) -> None:
        self.push_screen(MainMenuScreen())


def run() -> int:
    """启动 TUI。"""
    app = GuandanApp()
    return app.run() or 0


if __name__ == "__main__":
    import sys

    sys.exit(run())

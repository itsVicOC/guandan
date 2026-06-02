"""断点续局屏。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static


class LoadSaveScreen(Screen):
    """断点续局屏（M5 持久化阶段再做完整）。"""

    BINDINGS = [
        ("escape", "back", "返回"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Center():
            with Vertical(id="load-box"):
                yield Static("💾 断点续局", id="load-title")
                yield Static("（M5 持久化阶段实现）", id="load-empty")
                yield Static("当前 ~/.guandan/savegame.json 不存在", id="load-hint")
                yield Button("← 返回", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#load-title", Static).styles.text_style = "bold"
        self.query_one("#load-title", Static).styles.color = "yellow"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()

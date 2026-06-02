"""历史战绩屏。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static


class HistoryScreen(Screen):
    """历史战绩屏（M5 持久化阶段再做完整）。"""

    BINDINGS = [
        ("escape", "back", "返回"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Center():
            with Vertical(id="hist-box"):
                yield Static("📊 历史战绩", id="hist-title")
                yield Static("（M5 持久化阶段实现）", id="hist-empty")
                yield Static("当前 ~/.guandan/profile.json 不存在或为空", id="hist-hint")
                yield Button("← 返回", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#hist-title", Static).styles.text_style = "bold"
        self.query_one("#hist-title", Static).styles.color = "yellow"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()

"""规则说明屏。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from ...ui.content import GAME_RULES_TEXT, TUI_CONTROLS_TEXT


class RuleScreen(Screen):
    """规则说明屏。"""

    BINDINGS = [
        ("escape", "back", "返回"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Center(), Vertical(id="rule-box"):
            yield Static("📜 掼蛋规则", id="rule-title")
            with VerticalScroll(id="rule-scroll"):
                yield Static(f"{GAME_RULES_TEXT}\n{TUI_CONTROLS_TEXT}")
            yield Button("← 返回", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#rule-title", Static).styles.text_style = "bold"
        self.query_one("#rule-title", Static).styles.color = "yellow"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()

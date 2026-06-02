"""主菜单屏。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static


class MainMenuScreen(Screen):
    """主菜单。"""

    BINDINGS = [
        ("1", "new_game", "开始新局"),
        ("2", "load_save", "继续上次的牌局"),
        ("3", "history", "历史战绩"),
        ("4", "rules", "规则说明"),
        ("5", "quit", "退出"),
        ("q", "quit", "退出"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Center():
            with Vertical(id="menu-box"):
                yield Static("🀄 掼蛋 🀄", id="title")
                yield Static("v0.2.0 · M1", id="subtitle")
                yield Button("1. 开始新局", id="btn-new", variant="primary")
                yield Button("2. 继续上次的牌局", id="btn-load")
                yield Button("3. 历史战绩", id="btn-history")
                yield Button("4. 规则说明", id="btn-rules")
                yield Button("5. 退出", id="btn-quit")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#title", Static).styles.text_style = "bold"
        self.query_one("#title", Static).styles.color = "yellow"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-new":
            self.action_new_game()
        elif bid == "btn-load":
            self.action_load_save()
        elif bid == "btn-history":
            self.action_history()
        elif bid == "btn-rules":
            self.action_rules()
        elif bid == "btn-quit":
            self.action_quit()

    def action_new_game(self) -> None:
        from .difficulty import DifficultySelectScreen

        self.app.push_screen(DifficultySelectScreen())

    def action_load_save(self) -> None:
        from .load_save import LoadSaveScreen

        self.app.push_screen(LoadSaveScreen())

    def action_history(self) -> None:
        from .history import HistoryScreen

        self.app.push_screen(HistoryScreen())

    def action_rules(self) -> None:
        from .rule import RuleScreen

        self.app.push_screen(RuleScreen())

    def action_quit(self) -> None:
        self.app.exit()

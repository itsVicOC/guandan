"""主菜单屏。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static


class MainMenuScreen(Screen):
    """主菜单。"""

    CSS = """
    MainMenuScreen {
        align: center middle;
        background: #101512;
        color: #eee8d9;
    }

    #home-center {
        width: 100%;
        height: 1fr;
        align: center middle;
    }

    #home-shell {
        width: 90;
        max-width: 96;
        height: auto;
        padding: 1 2;
        border: round #d6b35a;
        background: #18211d;
    }

    #brand-panel {
        width: 35;
        min-width: 30;
        padding: 1 2 1 1;
    }

    #action-panel {
        width: 42;
        min-width: 34;
        padding: 1 1 1 2;
        border-left: solid #344237;
    }

    #title {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: #ffd978;
        padding-bottom: 1;
    }

    #subtitle {
        width: 100%;
        text-align: center;
        color: #9fb7a6;
        padding-bottom: 1;
    }

    #seat-card {
        width: 100%;
        height: auto;
        padding: 1 2;
        margin-top: 1;
        border: round #60765f;
        background: #111815;
    }

    #seat-title {
        width: 100%;
        text-align: center;
        color: #d6b35a;
        text-style: bold;
        padding-bottom: 1;
    }

    #seat-map {
        width: 100%;
        text-align: center;
        color: #eee8d9;
        padding-bottom: 1;
    }

    #table-note {
        width: 100%;
        text-align: center;
        color: #8fa496;
    }

    #rule-strip {
        width: 100%;
        margin-top: 1;
        padding: 1 2;
        border: tall #344237;
        color: #cdd7c8;
        background: #121a17;
    }

    #action-title {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: #f2d98b;
        padding-bottom: 1;
    }

    .menu-button {
        width: 100%;
        margin-bottom: 1;
    }

    #btn-quit {
        margin-top: 1;
    }

    #status-line {
        width: 100%;
        margin-top: 1;
        color: #8fa496;
        text-align: center;
    }
    """

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
        with Center(id="home-center"):
            with Horizontal(id="home-shell"):
                with Vertical(id="brand-panel"):
                    yield Static("掼蛋", id="title")
                    yield Static("本地四人牌局", id="subtitle")
                    with Vertical(id="seat-card"):
                        yield Static("座位", id="seat-title")
                        yield Static("        北\n\n西              东\n\n        南", id="seat-map")
                        yield Static("你默认坐东，队友在西", id="table-note")
                    yield Static("逆时针行牌 · 双副牌 · 逢人配", id="rule-strip")
                with Vertical(id="action-panel"):
                    yield Static("牌局大厅", id="action-title")
                    yield Button("1  开始新局", id="btn-new", variant="primary", classes="menu-button")
                    yield Button("2  继续上次的牌局", id="btn-load", classes="menu-button")
                    yield Button("3  历史战绩", id="btn-history", classes="menu-button")
                    yield Button("4  规则说明", id="btn-rules", classes="menu-button")
                    yield Button("5  退出", id="btn-quit", variant="error", classes="menu-button")
                    yield Static("选择后进入对应页面", id="status-line")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#btn-new", Button).focus()

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

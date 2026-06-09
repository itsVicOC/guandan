"""难度选择屏。"""
from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from ...engine.card import RANK_2

DIFFICULTIES = [
    ("新手", "随机贪心，记牌弱"),
    ("进阶", "贪心 + 简单估值"),
    ("高手", "贪心 + 记牌 + 协作分"),
    ("职业", "IS-MCTS + 完整估值"),
    ("戴长胜", "IS-MCTS + 风格化参数（致敬）"),
]


class DifficultySelectScreen(Screen):
    """难度选择。"""

    CSS = """
    DifficultySelectScreen {
        align: center middle;
        background: #101512;
        color: #eee8d9;
    }

    #diff-center {
        width: 100%;
        height: 1fr;
        align: center middle;
    }

    #diff-shell {
        width: 92;
        max-width: 98;
        height: auto;
        padding: 1 2;
        border: round #d6b35a;
        background: #18211d;
    }

    #diff-summary {
        width: 30;
        min-width: 28;
        padding: 1 2 1 1;
    }

    #diff-options {
        width: 48;
        min-width: 40;
        padding: 1 1 1 2;
        border-left: solid #344237;
    }

    #diff-title {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: #ffd978;
        padding-bottom: 1;
    }

    #diff-sub {
        width: 100%;
        text-align: center;
        color: #9fb7a6;
        padding-bottom: 1;
    }

    #level-card {
        width: 100%;
        padding: 1 2;
        margin-top: 1;
        border: round #60765f;
        background: #111815;
    }

    #level-title {
        width: 100%;
        text-align: center;
        color: #d6b35a;
        text-style: bold;
        padding-bottom: 1;
    }

    #level-value {
        width: 100%;
        text-align: center;
        color: #eee8d9;
        text-style: bold;
    }

    #diff-note {
        width: 100%;
        margin-top: 1;
        padding: 1 2;
        border: tall #344237;
        color: #cdd7c8;
        background: #121a17;
    }

    #option-title {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: #f2d98b;
        padding-bottom: 1;
    }

    .difficulty-button {
        width: 100%;
        margin-bottom: 1;
    }

    #btn-back {
        width: 100%;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("1", "select_0", "新手"),
        ("2", "select_1", "进阶"),
        ("3", "select_2", "高手"),
        ("4", "select_3", "职业"),
        ("5", "select_4", "戴长胜"),
        ("escape", "back", "返回"),
    ]

    def __init__(self, previous_level: int = RANK_2) -> None:
        super().__init__()
        self.selected_difficulty: Optional[int] = None
        self.previous_level = previous_level

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Center(id="diff-center"):
            with Horizontal(id="diff-shell"):
                with Vertical(id="diff-summary"):
                    yield Static("AI 难度", id="diff-title")
                    yield Static("选择本局对手强度", id="diff-sub")
                    with Vertical(id="level-card"):
                        yield Static("本局级牌", id="level-title")
                        yield Static(str(self.previous_level), id="level-value")
                    yield Static("难度越高，AI 越重视牌型结构、协作和残局搜索。", id="diff-note")
                with Vertical(id="diff-options"):
                    yield Static("选择档位", id="option-title")
                    for i, (name, desc) in enumerate(DIFFICULTIES, start=1):
                        yield Button(
                            f"{i}  {name:<4}  {desc}",
                            id=f"btn-diff-{i}",
                            classes="difficulty-button",
                        )
                    yield Button("返回", id="btn-back", variant="default")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#btn-diff-1", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid and bid.startswith("btn-diff-"):
            idx = int(bid.split("-")[-1]) - 1
            self._start_game(idx)
        else:
            self.app.pop_screen()

    def action_select_0(self) -> None:
        self._start_game(0)

    def action_select_1(self) -> None:
        self._start_game(1)

    def action_select_2(self) -> None:
        self._start_game(2)

    def action_select_3(self) -> None:
        self._start_game(3)

    def action_select_4(self) -> None:
        self._start_game(4)

    def action_back(self) -> None:
        self.app.pop_screen()

    def _start_game(self, difficulty: int) -> None:
        from ...ai import AINotImplementedError, make_strategy
        from .error import ErrorModal
        from .game import GameScreen

        try:
            make_strategy(difficulty)
        except AINotImplementedError as e:
            self.app.push_screen(ErrorModal(str(e), title="AI 档位未上线"))
            return
        screen = GameScreen(
            difficulty=difficulty,
            level=self.previous_level,
        )
        self.app.push_screen(screen)

"""难度选择屏。"""
from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from ...engine.card import RANK_2, RANK_A


DIFFICULTIES = [
    ("新手", "随机贪心，记牌弱"),
    ("进阶", "贪心 + 简单估值"),
    ("高手", "贪心 + 记牌 + 协作分"),
    ("职业", "IS-MCTS + 完整估值"),
    ("戴长胜", "IS-MCTS + 风格化参数（致敬）"),
]


class DifficultySelectScreen(Screen):
    """难度选择。"""

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
        with Center():
            with Vertical(id="diff-box"):
                yield Static("选择 AI 难度", id="diff-title")
                yield Static(f"（本局级牌 {self.previous_level}）", id="diff-sub")
                for i, (name, desc) in enumerate(DIFFICULTIES, start=1):
                    yield Button(
                        f"{i}. {name}  —  {desc}",
                        id=f"btn-diff-{i}",
                    )
                yield Button("← 返回", id="btn-back", variant="default")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#diff-title", Static).styles.text_style = "bold"
        self.query_one("#diff-title", Static).styles.color = "yellow"

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
        from .game import GameScreen

        screen = GameScreen(
            difficulty=difficulty,
            level=self.previous_level,
        )
        self.app.push_screen(screen)

"""牌桌屏（M1 核心）。"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Center, Grid, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from ...cli import _ai_play
from ...engine.card import Card
from ...engine.hand import Hand, Pattern, PatternType, sort_cards
from ...engine.state import (
    SEAT_NAMES,
    IllegalPlayError,
    make_initial_state,
    pass_turn,
    play_pattern,
    team_of,
)


class OpponentWidget(Static):
    """显示对手一方的信息：名字 + 剩余张数 + AI 等级。"""

    DEFAULT_CSS = """
    OpponentWidget {
        width: 1fr;
        height: 3;
        content-align: center middle;
        border: round $primary;
    }
    """

    def __init__(self, player: int, seat_name: str, ai_label: str, **kwargs) -> None:
        super().__init__("[X] AI\n27 张", **kwargs)
        self._player = player
        self._seat_name = seat_name
        self._ai_label = ai_label
        self._hand_size = 27
        self._finished = False
        self._is_turn = False

    def on_mount(self) -> None:
        self._do_render()

    def update_state(
        self, hand_size: int, finished: bool, is_turn: bool
    ) -> None:
        self._hand_size = hand_size
        self._finished = finished
        self._is_turn = is_turn
        self._do_render()

    def _do_render(self) -> None:
        marker = " [bold yellow]←[/bold yellow]" if self._is_turn else ""
        done = "（已出完）" if self._finished else f"{self._hand_size:2d} 张"
        text = f"[bold][{self._seat_name}][/bold] [dim]{self._ai_label}[/dim]\n{done}{marker}"
        self.update(text)


class TableWidget(Static):
    """中央出牌区。"""

    def __init__(self, **kwargs) -> None:
        super().__init__("（空）", **kwargs)
        self._table_patterns: List[Pattern] = []
        self._players: List[int] = []

    def on_mount(self) -> None:
        self._do_render()

    def update_table(self, patterns: List[Pattern], players: List[int]) -> None:
        self._table_patterns = patterns
        self._players = players
        self._do_render()

    def _pattern_str(self, p: Pattern) -> str:
        if p.type == PatternType.SINGLE:
            return p.cards[0].rich
        if p.type == PatternType.PAIR:
            return f"对{p.cards[0].rich}"
        cards_str = " ".join(c.rich for c in p.cards)
        # 不加外层 [] 避免 rich 解析器把 ♠ 等 Unicode 当成 tag
        return f"{p.type.value}  {cards_str}"

    def _do_render(self) -> None:
        if not self._table_patterns:
            self.update("（空）")
            return
        lines = []
        for p, who in zip(self._table_patterns, self._players):
            lines.append(f"  [bold]{SEAT_NAMES[who]}[/bold]: {self._pattern_str(p)}")
        self.update("\n".join(lines))


class HandWidget(Static):
    """占位：玩家手牌。所有交互状态由 GameScreen 持有。"""

    pass


class GameScreen(Screen):
    """牌桌屏。"""

    BINDINGS = [
        ("left", "cursor_left", "←"),
        ("right", "cursor_right", "→"),
        ("up", "cursor_left", "←"),
        ("down", "cursor_right", "→"),
        ("space", "toggle_select", "选牌"),
        ("enter", "play", "出牌"),
        ("p", "pass", "过牌"),
        ("t", "hint", "提示"),
        ("b", "claim", "报牌"),
        ("?", "rules", "规则"),
        ("escape", "back", "返回"),
    ]

    def __init__(self, *args, difficulty: int = 2, level: int = 2, human: int = 0, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.difficulty = difficulty
        self.level = level
        self.human = human
        self.state = None
        self.message = ""
        # 交互状态（不放在 widget 上以避免 textual 命名冲突）
        self._hand_cards: List[Card] = []
        self._hand_selected = set()
        self._hand_cursor = 0

    def compose(self) -> None:
        yield Header()
        with Vertical():
            # 顶部对手区：西 + 北，Grid 确保两者都可见
            with Horizontal(id="top-opponents"):
                yield OpponentWidget(2, "西", "AI·进阶", id="opp-west")
                yield OpponentWidget(3, "北", "AI·进阶", id="opp-north")
            with Center():
                yield TableWidget(id="table")
            # 底部：南
            with Horizontal(id="bottom-area"):
                yield OpponentWidget(1, "南", "AI·进阶", id="opp-south")
            yield Static("hand", id="my-hand")
            yield Static("ready", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        import random

        self.state = make_initial_state(
            level=self.level, first_player=self.human, seed=random.randint(1, 10000)
        )
        self._refresh_all()
        self.set_timer(0.3, self._maybe_ai_turn)

    def _refresh_all(self) -> None:
        s = self.state
        for p, wid in [(1, "opp-south"), (2, "opp-west"), (3, "opp-north")]:
            w = self.query_one(f"#{wid}", OpponentWidget)
            w.update_state(
                hand_size=len(s.hands[p]),
                finished=p in s.finish_order,
                is_turn=s.turn_index == p,
            )
        # 更新玩家手牌（在自己管理的状态 + 外部渲染）
        self._hand_cards = sort_cards(s.hands[self.human])
        if self._hand_cursor >= len(self._hand_cards):
            self._hand_cursor = max(0, len(self._hand_cards) - 1)
        self._do_render_hand()
        tbl = self.query_one("#table", TableWidget)
        tbl.update_table(s.table, [self._last_player_of(p) for p in s.table])
        # 状态信息写入 screen title
        turn_name = SEAT_NAMES[s.turn_index]
        if s.finished:
            order_str = " > ".join(SEAT_NAMES[p] for p in s.finish_order)
            self.sub_title = f"本局结束！名次：{order_str}"
        elif s.turn_index == self.human:
            hand_size = len(s.hands[self.human])
            self.sub_title = f"轮到你（{turn_name}）· {hand_size} 张"
        else:
            self.sub_title = f"等待 {turn_name} 出牌中..."

    def _do_render_hand(self) -> None:
        if not self._hand_cards:
            self.query_one("#my-hand", Static).update("（无牌）")
            return
        parts = []
        for i, c in enumerate(self._hand_cards):
            marker = "  "
            if i == self._hand_cursor:
                marker = "[bold yellow]▶ [/bold yellow]" if c not in self._hand_selected else "[bold yellow]★ [/bold yellow]"
            elif c in self._hand_selected:
                marker = "[green]■ [/green]"
            parts.append(f"{marker}{c.rich}")
        self.query_one("#my-hand", Static).update("  ".join(parts))

    def _last_player_of(self, p: Pattern) -> int:
        for ev in reversed(self.state.history):
            if hasattr(ev, "pattern") and getattr(ev, "pattern", None) == p:
                return ev.player
        return 0

    def action_cursor_left(self) -> None:
        if not self._hand_cards:
            return
        self._hand_cursor = (self._hand_cursor - 1) % len(self._hand_cards)
        self._do_render_hand()

    def action_cursor_right(self) -> None:
        if not self._hand_cards:
            return
        self._hand_cursor = (self._hand_cursor + 1) % len(self._hand_cards)
        self._do_render_hand()

    def action_toggle_select(self) -> None:
        if not self._hand_cards:
            return
        c = self._hand_cards[self._hand_cursor]
        if c in self._hand_selected:
            self._hand_selected.discard(c)
        else:
            self._hand_selected.add(c)
        self._do_render_hand()

    def action_play(self) -> None:
        if self.state.finished or self.state.turn_index != self.human:
            return
        sel = [self._hand_cards[i] for i in sorted(
            i for i, c in enumerate(self._hand_cards) if c in self._hand_selected
        )]
        if not sel:
            self.sub_title = "未选牌"
            return
        from ...engine.rules.patterns import find_complete_pattern

        p = find_complete_pattern(sel, self.state.wild_card)
        if p is None:
            self.sub_title = "这组牌不是合法牌型"
            return
        try:
            play_pattern(self.state, self.human, p)
            self._hand_selected.clear()
            self._refresh_all()
            self.set_timer(0.3, self._maybe_ai_turn)
        except IllegalPlayError as e:
            self.sub_title = f"非法：{e}"

    def action_pass(self) -> None:
        if self.state.finished or self.state.turn_index != self.human:
            return
        try:
            pass_turn(self.state, self.human)
            self._refresh_all()
            self.set_timer(0.3, self._maybe_ai_turn)
        except IllegalPlayError as e:
            self.sub_title = f"非法：{e}"

    def action_hint(self) -> None:
        if self.state.finished or self.state.turn_index != self.human:
            return
        from ...cli import _greedy_ai_select

        p = _greedy_ai_select(self.state, self.human)
        if p is None:
            self.sub_title = "（无提示：过牌）"
        else:
            cards_str = " ".join(c.rich for c in p.cards)
            self.sub_title = f"💡 提示：{p.type.value} [{cards_str}]"

    def action_claim(self) -> None:
        from ...engine.state import claim

        claim(self.state, self.human, len(self.state.hands[self.human]))
        self.sub_title = f"📢 你报了 {len(self.state.hands[self.human])} 张"

    def action_rules(self) -> None:
        from .rule import RuleScreen

        self.app.push_screen(RuleScreen())

    def action_back(self) -> None:
        self.app.pop_screen()

    def _maybe_ai_turn(self) -> None:
        if self.state.finished:
            self._refresh_all()
            return
        try:
            while (
                not self.state.finished
                and self.state.turn_index != self.human
            ):
                _ai_play(self.state, self.state.turn_index)
                self._refresh_all()
                import time
                time.sleep(0.05)
        except IllegalPlayError as e:
            self.sub_title = f"AI 错误：{e}"
        self._refresh_all()

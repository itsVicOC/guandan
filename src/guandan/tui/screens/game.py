"""牌桌屏（M1 核心，M2 接入 AI 包，M5 存储集成）。"""
from __future__ import annotations

import asyncio
import random
import time
from typing import List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Center, Grid, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from ...ai import AINotImplementedError, make_strategy, play_or_pass
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
from ...storage import (
    delete_savegame,
    load_profile,
    save_game,
    save_history,
    save_profile,
    update_statistics,
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
        self._passed: List[int] = []  # 本轮已过牌的玩家

    def on_mount(self) -> None:
        self._do_render()

    def update_table(
        self,
        patterns: List[Pattern],
        players: List[int],
        passed: List[int] = None,
    ) -> None:
        self._table_patterns = patterns
        self._players = players
        self._passed = passed if passed is not None else []
        self._do_render()

    def _pattern_str(self, p: Pattern) -> str:
        if p.type == PatternType.SINGLE:
            return p.cards[0].rich
        if p.type == PatternType.PAIR:
            return f"对{p.cards[0].rich}"
        cards_str = " ".join(c.rich for c in p.cards)
        return f"{p.type.value}  {cards_str}"

    def _do_render(self) -> None:
        if not self._table_patterns and not self._passed:
            self.update("（空）")
            return
        lines = []
        # 出牌
        for p, who in zip(self._table_patterns, self._players):
            lines.append(f"  [bold]{SEAT_NAMES[who]}[/bold]: {self._pattern_str(p)}")
        # 过牌（灰色显示）
        for who in self._passed:
            lines.append(f"  [dim]{SEAT_NAMES[who]}: 过牌[/dim]")
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
        # 注入 AI 策略（档 3/4 会在 DifficultySelectScreen._start_game 阻断）
        # 这里再兜底一次：万一直接构造 GameScreen 时给了一个未实现的档
        try:
            self._strategy = make_strategy(difficulty)
        except AINotImplementedError:
            # 降级到 档 1 (进阶)
            self._strategy = make_strategy(1)
            self.difficulty = 1
        self._ai_rng = random.Random()
        # 交互状态（不放在 widget 上以避免 textual 命名冲突）
        self._hand_cards: List[Card] = []
        self._hand_selected = set()
        self._hand_cursor = 0
        # M5 存储：追踪对局元数据
        self._game_id = f"game_{int(time.time())}"
        self._start_time = time.time()
        self._seed = random.randint(1, 10000)
        self._game_saved = False  # 防止重复保存

    def compose(self) -> None:
        ai_label = f"AI·{self._strategy.name}"
        yield Header()
        with Vertical():
            # 顶部对手区：西 + 北，Grid 确保两者都可见
            with Horizontal(id="top-opponents"):
                yield OpponentWidget(2, "西", ai_label, id="opp-west")
                yield OpponentWidget(3, "北", ai_label, id="opp-north")
            with Center():
                yield TableWidget(id="table")
            # 底部：南
            with Horizontal(id="bottom-area"):
                yield OpponentWidget(1, "南", ai_label, id="opp-south")
            yield Static("hand", id="my-hand")
            yield Static("ready", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.state = make_initial_state(
            level=self.level, first_player=self.human, seed=self._seed
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
        # 提取本轮已过牌的玩家（自上次 TurnPlayed 之后的 Pass 事件）
        passed_players = self._passed_in_current_trick()
        tbl.update_table(
            s.table,
            [self._last_player_of(p) for p in s.table],
            passed=passed_players,
        )
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

    def _passed_in_current_trick(self) -> List[int]:
        """提取本轮（自上次 TurnPlayed 之后）已过牌的玩家，按过牌顺序。"""
        from ...engine.events import Pass, TurnPlayed
        # 找到最后一次 TurnPlayed 的索引
        last_turn_idx = -1
        for i, ev in enumerate(self.state.history):
            if isinstance(ev, TurnPlayed):
                last_turn_idx = i
        # 在 last_turn_idx 之后的 Pass 事件
        passed = []
        for ev in self.state.history[last_turn_idx + 1:]:
            if isinstance(ev, Pass):
                passed.append(ev.player)
        return passed

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
        # 提示固定用 档 1 (进阶) —— 用户决策：避免新手档提示太弱 / 高档太怪
        hint_strategy = make_strategy(1)
        p = hint_strategy.select_pattern(self.state, self.human)
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
        # M5: 退出时保存存档（如果游戏未完成）
        if not self.state.finished and not self._game_saved:
            try:
                ai_difficulties = [
                    None if i == self.human else self.difficulty for i in range(4)
                ]
                save_game(
                    state=self.state,
                    game_id=self._game_id,
                    player_seat=self.human,
                    ai_difficulties=ai_difficulties,
                    seed=self._seed,
                )
            except Exception:
                # 保存失败不影响退出
                pass
        self.app.pop_screen()

    def _maybe_ai_turn(self) -> None:
        if self.state.finished:
            self._refresh_all()
            # M5: 游戏结束，保存历史和统计
            if not self._game_saved:
                self._save_game_result()
            return
        try:
            # 阶段 1：trick 进行中（table 有牌），让 AIs 压
            while (
                not self.state.finished
                and self.state.turn_index != self.human
                and self.state.table
            ):
                play_or_pass(
                    self.state,
                    self.state.turn_index,
                    self._strategy,
                    self._ai_rng,
                )
                self._refresh_all()
                import time
                time.sleep(0.05)
            # 阶段 2：trick 刚结束（table 空），新 leader 是 AI → 让它出 1 张
            # 出 1 张后**退出**，让人类决定是否"过"（不能继续循环让所有 AI 出完）
            if (
                not self.state.finished
                and not self.state.table
                and self.state.turn_index != self.human
            ):
                play_or_pass(
                    self.state,
                    self.state.turn_index,
                    self._strategy,
                    self._ai_rng,
                )
                self._refresh_all()
        except IllegalPlayError as e:
            self.sub_title = f"AI 错误：{e}"
        self._refresh_all()
        # 检查游戏是否刚结束
        if self.state.finished and not self._game_saved:
            self._save_game_result()

    def _save_game_result(self) -> None:
        """保存游戏结果（历史和统计）。"""
        if self._game_saved:
            return
        self._game_saved = True

        try:
            # 计算对局时长
            duration = int(time.time() - self._start_time)

            # AI 难度列表
            ai_difficulties = [
                None if i == self.human else self.difficulty for i in range(4)
            ]

            # 保存历史记录
            save_history(
                state=self.state,
                game_id=self._game_id,
                player_seat=self.human,
                ai_difficulties=ai_difficulties,
                seed=self._seed,
                duration_seconds=duration,
            )

            # 更新统计
            player_rank = self.state.finish_order.index(self.human) + 1
            profile = load_profile()
            update_statistics(profile, player_rank=player_rank, difficulty=self.difficulty)
            save_profile(profile)

            # 删除存档（如果存在）
            delete_savegame()

        except Exception as e:
            # 保存失败不影响游戏，但记录错误
            self.sub_title = f"保存失败：{e}"

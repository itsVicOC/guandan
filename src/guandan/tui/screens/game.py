"""牌桌屏（M1 核心，M2 接入 AI 包，M5 存储集成，M6 TUI 优化）。"""
from __future__ import annotations

import random
import time
from typing import List, Optional

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from ...ai import AINotImplementedError, make_strategy, play_or_pass
from ...engine.card import Card, Suit
from ...engine.events import Pass, TurnPlayed
from ...engine.hand import Pattern, PatternType, sort_cards
from ...engine.rules.tributes import apply_tribute_flow
from ...engine.state import (
    SEAT_NAMES,
    GameState,
    IllegalPlayError,
    make_initial_state,
    pass_turn,
    play_pattern,
)
from ...engine.trick import (
    current_table_players,
    current_trick_actions,
    last_player_of_pattern,
    locked_passed_players,
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
        height: 4;
        content-align: center middle;
        border: round #60765f;
        background: #111815;
        color: #eee8d9;
        padding: 0 1;
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
        marker = " [bold #ffd978]行动中[/bold #ffd978]" if self._is_turn else ""
        done = "[green]已出完[/green]" if self._finished else f"{self._hand_size:2d} 张"
        text = (
            f"[bold #ffd978]{self._seat_name}家[/bold #ffd978] "
            f"[dim]{self._ai_label}[/dim]{marker}\n"
            f"{done}"
        )
        self.update(text)


def _tui_card(card: Card, *, selected: bool = False, cursor: bool = False, wild: bool = False) -> str:
    """终端专用牌面：用中文花色、符号和固定底色降低对终端配色的依赖。"""
    if card.is_big_joker:
        body = "大王"
        style = "bold #101010 on #ffd84d"
    elif card.is_small_joker:
        body = "小王"
        style = "bold #101010 on #ffd84d"
    else:
        suit_meta = {
            Suit.HEARTS: ("红", "♥", "bold #fff4f4 on #7a1f1f"),
            Suit.DIAMONDS: ("方", "♦", "bold #fff4ff on #733078"),
            Suit.SPADES: ("黑", "♠", "bold #101010 on #e5e5e5"),
            Suit.CLUBS: ("梅", "♣", "bold #10201c on #65d4bf"),
        }[card.suit]
        suit_text, suit_symbol, style = suit_meta
        body = f"{suit_text}{_rank_label(card)}{suit_symbol}"

    label = f"{body}配" if wild else body

    if selected and cursor:
        return _styled_card("bold #101010 on #ffd84d", f"▶{label}✓")
    if selected:
        return _styled_card("bold #101010 on #ffd84d", f"✓{label}✓")
    if cursor:
        return _styled_card("bold #ffffff on #2457d6", f"▶{label}◀")
    if wild:
        return _styled_card("bold #101010 on #75d575", f"★{label}")
    return _styled_card(style, f" {label} ")


def _styled_card(style: str, text: str) -> str:
    return f"[{style}]{escape(text)}[/]"


def _rank_label(card: Card) -> str:
    if card.rank == 14:
        return "A"
    if card.rank == 13:
        return "K"
    if card.rank == 12:
        return "Q"
    if card.rank == 11:
        return "J"
    return str(card.rank)


def _wild_card_from_hands(level: int, hands: list[list[Card]]) -> Optional[Card]:
    for hand in hands:
        for card in hand:
            if card.rank == level and card.suit == Suit.HEARTS:
                return card
    return None


class PlayerStatusWidget(Static):
    """显示玩家自己的状态。"""

    DEFAULT_CSS = """
    PlayerStatusWidget {
        width: 1fr;
        height: 4;
        content-align: center middle;
        border: round #d6b35a;
        background: #18211d;
        color: #eee8d9;
        padding: 0 1;
    }
    """

    def update_state(self, seat_name: str, hand_size: int, is_turn: bool) -> None:
        marker = " [bold #ffd978]行动中[/bold #ffd978]" if is_turn else ""
        self.update(
            f"[bold #ffd978]{seat_name}家[/bold #ffd978] [dim]你[/dim]{marker}\n"
            f"{hand_size:2d} 张"
        )


class TableWidget(Static):
    """中央出牌区。"""

    DEFAULT_CSS = """
    TableWidget {
        height: 12;
        border: round #d6b35a;
        padding: 1 2;
        background: #121a17;
        color: #eee8d9;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("（空）", **kwargs)
        self._table_patterns: List[Pattern] = []
        self._players: List[int] = []
        self._passed: List[int] = []  # 本轮已过牌的玩家
        self._seat_actions: dict[int, tuple[str, Pattern | None]] = {}

    def on_mount(self) -> None:
        self._do_render()

    def update_table(
        self,
        patterns: List[Pattern],
        players: List[int],
        passed: Optional[List[int]] = None,
        seat_actions: Optional[dict[int, tuple[str, Pattern | None]]] = None,
    ) -> None:
        self._table_patterns = patterns
        self._players = players
        self._passed = passed if passed is not None else []
        self._seat_actions = dict(seat_actions or {})
        self._do_render()

    def _pattern_str(self, p: Pattern) -> str:
        if p.type == PatternType.SINGLE:
            return _tui_card(p.cards[0])
        if p.type == PatternType.PAIR:
            return f"对{_tui_card(p.cards[0])}"
        cards_str = " ".join(_tui_card(c) for c in p.cards)
        return f"{p.type.value}  {cards_str}"

    def _do_render(self) -> None:
        if not self._table_patterns and not self._passed and not self._seat_actions:
            self.update("[bold #d6b35a]当前轮[/bold #d6b35a]\n\n[dim]桌面空，等待先手出牌[/dim]")
            return
        lines = ["[bold #d6b35a]当前轮[/bold #d6b35a]"]
        if self._table_patterns:
            top = self._table_patterns[-1]
            top_player = self._players[-1] if self._players else 0
            lines.append(
                f"[bold]最大[/bold] {SEAT_NAMES[top_player]}家 · {self._pattern_str(top)}"
            )
            recent = list(zip(self._table_patterns, self._players))[-5:]
            lines.append("")
            for p, who in recent:
                lines.append(f"  [#9fb7a6]{SEAT_NAMES[who]}:[/#9fb7a6] {self._pattern_str(p)}")
        if self._seat_actions:
            lines.append("")
            for who in (0, 3, 2, 1):
                action = self._seat_actions.get(who)
                if action is None:
                    lines.append(f"  [dim]{SEAT_NAMES[who]}: --[/dim]")
                    continue
                kind, pattern = action
                if kind == "pass":
                    lines.append(f"  [dim]{SEAT_NAMES[who]}: 过牌[/dim]")
                elif pattern is not None:
                    lines.append(
                        f"  [#9fb7a6]{SEAT_NAMES[who]}:[/#9fb7a6] {self._pattern_str(pattern)}"
                    )
        else:
            for who in self._passed:
                lines.append(f"  [dim]{SEAT_NAMES[who]}: 过牌[/dim]")
        self.update("\n".join(lines))


class HandWidget(Static):
    """占位：玩家手牌。所有交互状态由 GameScreen 持有。"""

    pass


class GameScreen(Screen):
    """牌桌屏。"""

    DEFAULT_CSS = """
    GameScreen {
        background: #101512;
        color: #eee8d9;
    }

    #game-shell {
        width: 100%;
        height: 1fr;
        padding: 0 1;
        background: #101512;
    }

    #table-layout {
        height: auto;
        grid-size: 3 3;
        grid-columns: 1fr 2fr 1fr;
        grid-rows: 4 12 4;
        grid-gutter: 1 1;
        padding: 1 0;
    }
    #opp-opposite {
        column-span: 3;
    }
    #status-bar {
        height: 4;
        padding: 0 2;
        border: round #60765f;
        background: #18211d;
        color: #cdd7c8;
    }
    #my-hand {
        min-height: 10;
        padding: 1 2;
        border: round #d6b35a;
        background: #0d1412;
        color: #eee8d9;
    }
    #round-actions {
        height: 3;
        align: center middle;
        padding: 0 2;
        background: #101512;
    }
    #btn-next-game {
        width: 24;
        margin-right: 2;
    }
    #btn-game-back {
        width: 18;
    }
    #action-log {
        height: 4;
        padding: 0 2;
        border: tall #344237;
        background: #121a17;
        color: #9fb7a6;
    }
    """

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
        ("n", "next_game", "下一局"),
        ("?", "rules", "规则"),
        ("escape", "back", "返回"),
    ]

    def __init__(
        self,
        *args,
        difficulty: int = 2,
        level: int = 2,
        human: int = 0,
        existing_state: Optional[GameState] = None,
        game_id: Optional[str] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.difficulty = difficulty
        self.level = level
        self.human = human
        self.state: Optional[GameState] = existing_state
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
        self._hand_selected_indices: set[int] = set()
        self._hand_cursor = 0
        self._last_action = "准备开始"
        self._displayed_table_actions: dict[int, tuple[str, Pattern | None]] = {}
        self._last_display_turn: Optional[int] = None
        # M5 存储：追踪对局元数据
        self._game_id = game_id or f"game_{int(time.time())}"
        self._start_time = time.time()
        self._seed = seed if seed is not None else random.randint(1, 10000)
        self._game_saved = False  # 防止重复保存

    def compose(self) -> ComposeResult:
        ai_label = f"AI·{self._strategy.name}"
        seats = self._visual_seats()
        yield Header()
        with Vertical(id="game-shell"):
            yield Static("status", id="status-bar")
            with Grid(id="table-layout"):
                yield OpponentWidget(seats["opposite"], SEAT_NAMES[seats["opposite"]], ai_label, id="opp-opposite")
                yield OpponentWidget(seats["left"], SEAT_NAMES[seats["left"]], ai_label, id="opp-left")
                yield TableWidget(id="table")
                yield OpponentWidget(seats["right"], SEAT_NAMES[seats["right"]], ai_label, id="opp-right")
                yield Static("")
                yield PlayerStatusWidget("", id="player-south")
                yield Static("")
            yield Static("hand", id="my-hand")
            with Horizontal(id="round-actions"):
                yield Button("N  下一局", id="btn-next-game", variant="success", disabled=True)
                yield Button("返回大厅", id="btn-game-back", variant="default")
            yield Static("ready", id="action-log")
        yield Footer()

    def on_mount(self) -> None:
        if self.state is None:
            first_player = random.randint(0, 3)
            self.state = make_initial_state(
                level=self.level, first_player=first_player, seed=self._seed
            )
        else:
            self.level = self.state.level
        self._refresh_all()
        self.set_timer(0.3, self._maybe_ai_turn)

    def _state(self) -> GameState:
        assert self.state is not None
        return self.state

    def _visual_seats(self) -> dict[str, int]:
        """返回以当前玩家为底部视角的左右和对面座位。"""
        return {
            "left": (self.human + 1) % 4,
            "opposite": (self.human + 2) % 4,
            "right": (self.human - 1) % 4,
        }

    def _refresh_all(self) -> None:
        s = self._state()
        seats = self._visual_seats()
        for p, wid in [
            (seats["left"], "opp-left"),
            (seats["opposite"], "opp-opposite"),
            (seats["right"], "opp-right"),
        ]:
            w = self.query_one(f"#{wid}", OpponentWidget)
            w.update_state(
                hand_size=len(s.hands[p]),
                finished=p in s.finish_order,
                is_turn=s.turn_index == p,
            )
        self.query_one("#player-south", PlayerStatusWidget).update_state(
            SEAT_NAMES[self.human],
            len(s.hands[self.human]),
            s.turn_index == self.human,
        )
        # 更新玩家手牌（在自己管理的状态 + 外部渲染）
        self._hand_cards = sort_cards(s.hands[self.human])
        if self._hand_cursor >= len(self._hand_cards):
            self._hand_cursor = max(0, len(self._hand_cards) - 1)
        self._hand_selected_indices = {
            i for i in self._hand_selected_indices if i < len(self._hand_cards)
        }
        self._do_render_hand()
        tbl = self.query_one("#table", TableWidget)
        # 提取本轮已过牌且仍被锁定的玩家
        table_players = self._current_table_players()
        passed_players = self._locked_passed_players()
        seat_actions = self._table_display_actions(table_players, passed_players)
        tbl.update_table(
            s.table,
            table_players,
            passed=passed_players,
            seat_actions=seat_actions,
        )
        # 状态信息写入 screen title
        turn_name = SEAT_NAMES[s.turn_index]
        if s.finished:
            order_str = " > ".join(SEAT_NAMES[p] for p in s.finish_order)
            if s.match_finished and s.winner_team is not None:
                winner = "东西" if s.winner_team == 0 else "南北"
                self.sub_title = f"比赛结束！{winner}方获胜 · 名次：{order_str}"
            else:
                next_level = self._next_round_level(s)
                self.sub_title = f"本局结束！名次：{order_str} · 下一局级牌 {next_level} · 按 N 继续"
        elif s.turn_index == self.human:
            hand_size = len(s.hands[self.human])
            self.sub_title = f"轮到你（{turn_name}）· {hand_size} 张"
        else:
            self.sub_title = f"等待 {turn_name} 出牌中..."
        self._render_status()
        self._refresh_round_actions()
        self.query_one("#action-log", Static).update(self._last_action)

    def _render_status(self) -> None:
        s = self._state()
        wild = _tui_card(s.wild_card, wild=True) if s.wild_card is not None else "无"
        leader = SEAT_NAMES[s.leader] if s.leader is not None else "-"
        table_players = self._current_table_players()
        top_player = SEAT_NAMES[table_players[-1]] if s.table and table_players else "-"
        finished = " > ".join(SEAT_NAMES[p] for p in s.finish_order) or "-"
        levels = self._visible_team_levels(s)
        text = (
            f"[bold #ffd978]级牌[/bold #ffd978] {s.level}   "
            f"[bold #ffd978]逢人配[/bold #ffd978] {wild}   "
            f"[bold #ffd978]当前[/bold #ffd978] {SEAT_NAMES[s.turn_index]}家   "
            f"[bold #ffd978]AI[/bold #ffd978] {self._strategy.name}\n"
            f"先手 {leader}家 · 最大 {top_player}家 · 队伍级数 东西:{levels[0]} 南北:{levels[1]} · 名次 {finished}"
        )
        if s.finished:
            if s.match_finished and s.winner_team is not None:
                winner = "东西" if s.winner_team == 0 else "南北"
                text += f" · 比赛结束：{winner}方获胜"
            else:
                text += f" · 下一局级牌 {self._next_round_level(s)}"
        self.query_one("#status-bar", Static).update(text)

    def _do_render_hand(self) -> None:
        if not self._hand_cards:
            self.query_one("#my-hand", Static).update(
                "[bold #d6b35a]你的手牌[/bold #d6b35a]\n[dim]本局已结束，点击“下一局”继续。[/dim]"
            )
            return
        parts = []
        for i, c in enumerate(self._hand_cards):
            selected = i in self._hand_selected_indices
            cursor = i == self._hand_cursor
            wild = self.state is not None and c == self.state.wild_card
            parts.append(_tui_card(c, selected=selected, cursor=cursor, wild=wild))
        rows = ["  ".join(parts[i : i + 7]) for i in range(0, len(parts), 7)]
        selected_count = len(self._hand_selected_indices)
        cursor_pos = self._hand_cursor + 1 if self._hand_cards else 0
        header = (
            "[bold #d6b35a]你的手牌[/bold #d6b35a]  "
            f"[#cdd7c8]光标 {cursor_pos}/{len(self._hand_cards)} · 已选 {selected_count} 张[/#cdd7c8]\n"
            "[dim]红♥ / 方♦ / 黑♠ / 梅♣ · ▶光标 · ✓选中 · ★逢人配 · 空格选牌 · 回车出牌[/dim]"
        )
        self.query_one("#my-hand", Static).update(f"{header}\n" + "\n".join(rows))

    def _refresh_round_actions(self) -> None:
        s = self._state()
        next_button = self.query_one("#btn-next-game", Button)
        next_button.disabled = not s.finished or s.match_finished
        if s.finished and s.match_finished:
            next_button.label = "比赛已结束"
        elif s.finished:
            next_button.label = f"N  下一局 · 级牌 {self._next_round_level(s)}"
        else:
            next_button.label = "N  下一局"

    def _next_round_level(self, state: GameState) -> int:
        if state.team_levels_final is None or not state.finish_order:
            return state.level
        head_team = state.finish_order[0] % 2
        return int(state.team_levels_final[head_team])

    def _next_round_first_player(self, state: GameState) -> int:
        return self._next_round_first_player_for_hands(state, state.hands)

    def _next_round_first_player_for_hands(
        self,
        state: GameState,
        hands: list[list[Card]],
    ) -> int:
        if not state.finish_order:
            return self.human
        next_level = self._next_round_level(state)
        result = apply_tribute_flow(
            list(state.finish_order),
            [list(hand) for hand in hands],
            level=next_level,
            wild_card=_wild_card_from_hands(next_level, hands),
        )
        return result.first_player

    def _next_round_team_levels(self, state: GameState) -> list[int]:
        if state.team_levels_final is None:
            return list(state.team_levels)
        return list(state.team_levels_final)

    def _visible_team_levels(self, state: GameState) -> list[int]:
        if state.finished and state.team_levels_final is not None:
            return list(state.team_levels_final)
        return list(state.team_levels)

    def _last_player_of(self, p: Pattern) -> int:
        return last_player_of_pattern(self._state(), p, default=0) or 0

    def _current_table_players(self) -> List[int]:
        """返回当前桌面每手牌对应的玩家，顺序与 `state.table` 一致。"""
        return current_table_players(self._state())

    def _current_trick_actions(self) -> List[TurnPlayed | Pass]:
        """从事件历史尾部提取当前 trick 的出牌/过牌事件。"""
        return current_trick_actions(self._state())

    def _locked_passed_players(self) -> List[int]:
        """提取本轮仍被锁定的过牌玩家，按过牌发生顺序。"""
        return locked_passed_players(self._state())

    def _table_display_actions(
        self,
        table_players: List[int],
        passed_players: List[int],
    ) -> dict[int, tuple[str, Pattern | None]]:
        """按座位保留出牌区显示，只在轮到该座位时清理其上一手。"""
        state = self._state()
        if state.finished:
            self._displayed_table_actions.clear()
            self._last_display_turn = None
            return {}

        if self._last_display_turn != state.turn_index:
            self._displayed_table_actions.pop(state.turn_index, None)
            self._last_display_turn = state.turn_index

        for player, pattern in zip(table_players, state.table):
            self._displayed_table_actions[player] = ("play", pattern)
        for player in passed_players:
            self._displayed_table_actions[player] = ("pass", None)

        return dict(self._displayed_table_actions)

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
        if self._hand_cursor in self._hand_selected_indices:
            self._hand_selected_indices.discard(self._hand_cursor)
        else:
            self._hand_selected_indices.add(self._hand_cursor)
        self._do_render_hand()

    def action_play(self) -> None:
        s = self._state()
        if s.finished or s.turn_index != self.human:
            return
        sel = [
            self._hand_cards[i]
            for i in sorted(self._hand_selected_indices)
            if i < len(self._hand_cards)
        ]
        if not sel:
            self.sub_title = "未选牌"
            self._last_action = "未选牌"
            self._refresh_all()
            return
        from ...engine.rules.patterns import find_complete_pattern

        p = find_complete_pattern(sel, s.wild_card)
        if p is None:
            self.sub_title = "这组牌不是合法牌型"
            self._last_action = "这组牌不是合法牌型"
            self._refresh_all()
            return
        try:
            play_pattern(s, self.human, p)
            self._last_action = f"你出牌：{p.type.value} · {' '.join(_tui_card(c) for c in p.cards)}"
            self._hand_selected_indices.clear()
            self._refresh_all()
            self.set_timer(0.3, self._maybe_ai_turn)
        except IllegalPlayError as e:
            self.sub_title = f"非法：{e}"
            self._last_action = f"非法：{e}"
            self._refresh_all()

    def action_pass(self) -> None:
        s = self._state()
        if s.finished or s.turn_index != self.human:
            return
        try:
            pass_turn(s, self.human)
            self._last_action = "你选择过牌"
            self._refresh_all()
            self.set_timer(0.3, self._maybe_ai_turn)
        except IllegalPlayError as e:
            self.sub_title = f"非法：{e}"
            self._last_action = f"非法：{e}"
            self._refresh_all()

    def action_hint(self) -> None:
        s = self._state()
        if s.finished or s.turn_index != self.human:
            return
        # 提示固定用 档 1 (进阶) —— 用户决策：避免新手档提示太弱 / 高档太怪
        hint_strategy = make_strategy(1)
        p = hint_strategy.select_pattern(s, self.human)
        if p is None:
            self.sub_title = "（无提示：过牌）"
            self._last_action = "提示：建议过牌"
        else:
            cards_str = " ".join(_tui_card(c) for c in p.cards)
            self.sub_title = f"💡 提示：{p.type.value} [{cards_str}]"
            self._last_action = f"提示：{p.type.value} · {cards_str}"
        self._refresh_all()

    def action_claim(self) -> None:
        from ...engine.state import claim

        s = self._state()
        claim(s, self.human, len(s.hands[self.human]))
        self.sub_title = f"📢 你报了 {len(s.hands[self.human])} 张"
        self._last_action = f"你报牌：{len(s.hands[self.human])} 张"
        self._refresh_all()

    def action_next_game(self) -> None:
        s = self._state()
        if not s.finished:
            self._last_action = "本局尚未结束，不能开始下一局"
            self._refresh_all()
            return
        if s.match_finished:
            self._last_action = "比赛已经结束，不能开始下一局"
            self._refresh_all()
            return
        if not self._game_saved:
            self._save_game_result()

        next_level = self._next_round_level(s)
        next_team_levels = self._next_round_team_levels(s)
        self.level = next_level
        self._seed = random.randint(1, 10000)
        self._game_id = f"game_{int(time.time())}"
        self._start_time = time.time()
        self._game_saved = False
        self._hand_selected_indices.clear()
        self._displayed_table_actions.clear()
        self._last_display_turn = None
        self._hand_cursor = 0
        next_state = make_initial_state(
            level=next_level,
            first_player=self.human,
            seed=self._seed,
            team_levels=next_team_levels,
        )
        tribute_result = apply_tribute_flow(
            list(s.finish_order),
            next_state.hands,
            level=next_state.level,
            wild_card=next_state.wild_card,
        )
        next_state.history.extend(tribute_result.events)
        next_first_player = tribute_result.first_player
        next_state.turn_index = next_first_player
        next_state.leader = next_first_player
        if next_state.history:
            shuffle = next_state.history[0]
            from ...engine.events import ShuffleDeal

            if isinstance(shuffle, ShuffleDeal):
                next_state.history[0] = ShuffleDeal(
                    level=shuffle.level,
                    wild_card=shuffle.wild_card,
                    hand_sizes=shuffle.hand_sizes,
                    first_player=next_first_player,
                    seed=shuffle.seed,
                    team_levels=shuffle.team_levels,
                )
        self.state = next_state
        tribute_note = "抗贡，" if tribute_result.resisted else ""
        self._last_action = (
            f"新一局开始：级牌 {next_level}，{tribute_note}{SEAT_NAMES[next_first_player]}家先手"
        )
        self._refresh_all()
        self.set_timer(0.3, self._maybe_ai_turn)

    def action_rules(self) -> None:
        from .rule import RuleScreen

        self.app.push_screen(RuleScreen())

    def action_back(self) -> None:
        s = self._state()
        if s.finished and not self._game_saved:
            self._save_game_result()
        # M5: 退出时保存存档（如果游戏未完成）
        if not s.finished and not self._game_saved:
            try:
                ai_difficulties = [
                    None if i == self.human else self.difficulty for i in range(4)
                ]
                save_game(
                    state=s,
                    game_id=self._game_id,
                    player_seat=self.human,
                    ai_difficulties=ai_difficulties,
                    seed=self._seed,
                )
            except Exception:
                # 保存失败不影响退出
                pass
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-next-game":
            self.action_next_game()
            event.stop()
        elif event.button.id == "btn-game-back":
            self.action_back()
            event.stop()

    def _maybe_ai_turn(self) -> None:
        s = self._state()
        if s.finished:
            self._refresh_all()
            # M5: 游戏结束，保存历史和统计
            if not self._game_saved:
                self._save_game_result()
            return
        ai_actions: list[str] = []
        ai_action_limit = 12
        try:
            while (
                not s.finished
                and s.turn_index != self.human
                and len(ai_actions) < ai_action_limit
            ):
                self._last_action = f"{SEAT_NAMES[s.turn_index]} 思考中..."
                self._refresh_all()
                player_before = s.turn_index
                history_len_before = len(s.history)
                play_or_pass(
                    s,
                    s.turn_index,
                    self._strategy,
                    self._ai_rng,
                )
                self._last_action = self._describe_ai_action(
                    s, player_before, history_len_before
                )
                ai_actions.append(self._last_action)
                self._refresh_all()
                import time
                time.sleep(0.05)
        except IllegalPlayError as e:
            self.sub_title = f"AI 错误：{e}"
        if ai_actions:
            self._last_action = "；".join(ai_actions[-4:])
        self._refresh_all()
        if (
            not s.finished
            and s.turn_index != self.human
            and len(ai_actions) >= ai_action_limit
        ):
            self.set_timer(0.1, self._maybe_ai_turn)
        # 检查游戏是否刚结束
        if s.finished and not self._game_saved:
            self._save_game_result()

    def _describe_ai_action(self, state: GameState, player: int, history_len_before: int) -> str:
        for ev in reversed(state.history[history_len_before:]):
            if isinstance(ev, TurnPlayed) and ev.player == player:
                cards = " ".join(_tui_card(c) for c in ev.pattern.cards)
                return f"{SEAT_NAMES[player]} 出牌：{ev.pattern.type.value} · {cards}"
            if isinstance(ev, Pass) and ev.player == player:
                return f"{SEAT_NAMES[player]} 过牌"
        return f"{SEAT_NAMES[player]} 过牌"

    def _save_game_result(self) -> None:
        """保存游戏结果（历史和统计）。"""
        if self._game_saved:
            return
        self._game_saved = True

        try:
            s = self._state()
            # 计算对局时长
            duration = int(time.time() - self._start_time)

            # AI 难度列表
            ai_difficulties = [
                None if i == self.human else self.difficulty for i in range(4)
            ]

            # 保存历史记录
            save_history(
                state=s,
                game_id=self._game_id,
                player_seat=self.human,
                ai_difficulties=ai_difficulties,
                seed=self._seed,
                duration_seconds=duration,
            )

            # 更新统计
            player_rank = s.finish_order.index(self.human) + 1 if self.human in s.finish_order else 4
            profile = load_profile()
            update_statistics(profile, player_rank=player_rank, difficulty=self.difficulty)
            save_profile(profile)

            # 删除存档（如果存在）
            delete_savegame()

        except Exception as e:
            # 保存失败不影响游戏，但记录错误
            self.sub_title = f"保存失败：{e}"

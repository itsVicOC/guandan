"""牌桌屏（M1 核心，M2 接入 AI 包，M5 存储集成，M6 TUI 优化）。"""
from __future__ import annotations

from typing import List, Optional, Sequence

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from ...engine.card import Card, Suit
from ...engine.events import Pass, TurnPlayed
from ...engine.hand import Pattern, PatternType, comparison_rank, sort_cards
from ...engine.rules.tributes import apply_tribute_flow
from ...engine.state import (
    SEAT_NAMES,
    GameState,
    IllegalPlayError,
)
from ...engine.trick import (
    current_trick_actions,
)
from ...ui.session import GameSession
from ..layout import MIN_COLUMNS, MIN_LINES, RECOMMENDED_COLUMNS, RECOMMENDED_LINES


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


def _rank_value_label(rank: int) -> str:
    if rank == 101:
        return "大王"
    if rank == 100:
        return "小王"
    if rank == 14:
        return "A"
    if rank == 13:
        return "K"
    if rank == 12:
        return "Q"
    if rank == 11:
        return "J"
    return str(rank)


def _pattern_type_label(pattern_type: PatternType) -> str:
    return {
        PatternType.SINGLE: "单张",
        PatternType.PAIR: "对子",
        PatternType.TRIPLE: "三张",
        PatternType.TRIPLE_PAIR: "三带二",
        PatternType.STRAIGHT: "顺子",
        PatternType.PAIR_SEQUENCE: "连对",
        PatternType.TRIPLE_SEQUENCE: "钢板",
        PatternType.BOMB: "炸弹",
        PatternType.STRAIGHT_FLUSH: "同花顺",
        PatternType.FOUR_JOKERS: "四王炸",
    }[pattern_type]


def _cards_text(cards: Sequence[Card]) -> str:
    return " ".join(card.compact for card in cards)


def _pattern_summary(pattern: Pattern, level: int) -> str:
    base_rank = _rank_value_label(pattern.rank)
    effective = comparison_rank(pattern, level)
    rank_text = f"{base_rank}(级牌)" if effective != pattern.rank else base_rank
    return (
        f"{_pattern_type_label(pattern.type)}"
        f" · 主牌 {rank_text}"
        f" · 张数 {len(pattern.cards)}"
        f" · [{_cards_text(pattern.cards)}]"
    )


def _play_rejection_message(selected: list[Card], pattern: Pattern, table_top: Pattern, level: int) -> str:
    return (
        "不能压过桌面："
        f"你选 [{_cards_text(selected)}]，识别为 {_pattern_summary(pattern, level)}；"
        f"桌面最大为 {_pattern_summary(table_top, level)}；"
        f"当前级牌 {_rank_value_label(level)} 会参与单/对/三/三带二/炸弹点数比较"
    )


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
        return f"{_pattern_type_label(p.type)}  {cards_str}"

    def _do_render(self) -> None:
        if not self._table_patterns and not self._passed and not self._seat_actions:
            self.update("[bold #d6b35a]当前轮[/bold #d6b35a]\n\n[dim]桌面空，等待先手出牌[/dim]")
            return

        top_player = self._players[-1] if self._table_patterns and self._players else None
        title = "[bold #d6b35a]当前轮[/bold #d6b35a]"
        if top_player is not None:
            title += f" · [bold]最大 {SEAT_NAMES[top_player]}家[/bold]"
        lines = [title]

        actions = dict(self._seat_actions)
        if not actions:
            actions.update({player: ("pass", None) for player in self._passed})
            actions.update(
                {player: ("play", pattern) for player, pattern in zip(self._players, self._table_patterns)}
            )

        for who in (0, 3, 2, 1):
            action = actions.get(who)
            seat = f"[#9fb7a6]{SEAT_NAMES[who]}:[/#9fb7a6]"
            marker = " [bold #ffd978]最大[/bold #ffd978]" if who == top_player else ""
            if action is None:
                lines.append(f"  {seat}{marker} [dim]--[/dim]")
                continue
            kind, pattern = action
            if kind == "pass":
                lines.append(f"  {seat}{marker} [dim]过牌[/dim]")
            elif pattern is not None:
                lines.append(f"  {seat}{marker} {self._pattern_str(pattern)}")
            else:
                lines.append(f"  {seat}{marker} [dim]--[/dim]")
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
        min-height: 9;
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
        Binding("left", "cursor_left", "←", priority=True),
        Binding("right", "cursor_right", "→", priority=True),
        Binding("up", "cursor_left", "←", priority=True),
        Binding("down", "cursor_right", "→", priority=True),
        Binding("space", "toggle_select", "选牌", priority=True),
        Binding("enter", "play", "出牌", priority=True),
        Binding("p", "pass", "过牌", priority=True),
        Binding("t", "hint", "提示", priority=True),
        Binding("b", "claim", "报牌", priority=True),
        Binding("n", "next_game", "下一局", priority=True),
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
        self.session = GameSession(
            difficulty=difficulty,
            level=level,
            human=human,
            existing_state=existing_state,
            game_id=game_id,
            seed=seed,
        )
        self.message = ""
        # 交互状态（不放在 widget 上以避免 textual 命名冲突）
        self._hand_cards: List[Card] = []
        self._hand_selected_indices: set[int] = set()
        self._hand_cursor = 0

    @property
    def difficulty(self) -> int:
        return self.session.difficulty

    @property
    def level(self) -> int:
        return self.session.level

    @property
    def human(self) -> int:
        return self.session.human

    @property
    def state(self) -> Optional[GameState]:
        return self.session.state

    @state.setter
    def state(self, value: Optional[GameState]) -> None:
        self.session.state = value

    @property
    def _strategy(self):
        return self.session.strategy

    @property
    def _ai_rng(self):
        return self.session.ai_rng

    @_ai_rng.setter
    def _ai_rng(self, value) -> None:
        self.session.ai_rng = value

    @property
    def _last_action(self) -> str:
        return self.session.last_action

    @_last_action.setter
    def _last_action(self, value: str) -> None:
        self.session.last_action = value

    @property
    def _game_saved(self) -> bool:
        return self.session.game_saved

    @_game_saved.setter
    def _game_saved(self, value: bool) -> None:
        self.session.game_saved = value

    @property
    def _displayed_table_actions(self) -> dict[int, tuple[str, Pattern | None]]:
        return self.session.displayed_table_actions

    @_displayed_table_actions.setter
    def _displayed_table_actions(self, value: dict[int, tuple[str, Pattern | None]]) -> None:
        self.session.displayed_table_actions = value

    @property
    def _last_display_turn(self) -> Optional[int]:
        return self.session.last_display_turn

    @_last_display_turn.setter
    def _last_display_turn(self, value: Optional[int]) -> None:
        self.session.last_display_turn = value

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
        self.session.ensure_started()
        self._refresh_all()
        self.set_timer(0.3, self._maybe_ai_turn)

    def _state(self) -> GameState:
        return self.session.require_state()

    def _visual_seats(self) -> dict[str, int]:
        """返回以当前玩家为底部视角的左右和对面座位。"""
        return self.session.visual_seats()

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
        cards_per_row = self._cards_per_hand_row()
        rows = [
            "  ".join(parts[i : i + cards_per_row])
            for i in range(0, len(parts), cards_per_row)
        ]
        selected_count = len(self._hand_selected_indices)
        cursor_pos = self._hand_cursor + 1 if self._hand_cards else 0
        size_tip = self._terminal_size_tip()
        header = (
            "[bold #d6b35a]你的手牌[/bold #d6b35a]  "
            f"[#cdd7c8]光标 {cursor_pos}/{len(self._hand_cards)} · 已选 {selected_count} 张{size_tip}[/#cdd7c8]\n"
            "[dim]红♥ / 方♦ / 黑♠ / 梅♣ · ▶光标 · ✓选中 · ★逢人配 · 空格选牌 · 回车出牌[/dim]"
        )
        self.query_one("#my-hand", Static).update(f"{header}\n" + "\n".join(rows))

    def _cards_per_hand_row(self) -> int:
        """Choose a stable hand wrap count from the live terminal width."""
        size = getattr(self.app, "size", None)
        width = size.width if size is not None else RECOMMENDED_COLUMNS
        usable_width = max(40, width - 10)
        return max(6, min(10, usable_width // 12))

    def _terminal_size_tip(self) -> str:
        size = getattr(self.app, "size", None)
        if size is None:
            return ""
        if size.width >= MIN_COLUMNS and size.height >= MIN_LINES:
            return ""
        return (
            f" · 建议终端 {RECOMMENDED_COLUMNS}x{RECOMMENDED_LINES}"
            f"（当前 {size.width}x{size.height}）"
        )

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
        return self.session.next_round_level(state)

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
        return self.session.next_round_team_levels(state)

    def _visible_team_levels(self, state: GameState) -> list[int]:
        del state
        return self.session.visible_team_levels()

    def _last_player_of(self, p: Pattern) -> int:
        return self.session.last_player_of(p)

    def _current_table_players(self) -> List[int]:
        """返回当前桌面每手牌对应的玩家，顺序与 `state.table` 一致。"""
        return self.session.current_table_players()

    def _current_trick_actions(self) -> List[TurnPlayed | Pass]:
        """从事件历史尾部提取当前 trick 的出牌/过牌事件。"""
        return current_trick_actions(self._state())

    def _locked_passed_players(self) -> List[int]:
        """提取本轮仍被锁定的过牌玩家，按过牌发生顺序。"""
        return self.session.locked_passed_players()

    def _table_display_actions(
        self,
        table_players: List[int],
        passed_players: List[int],
    ) -> dict[int, tuple[str, Pattern | None]]:
        """按座位保留出牌区显示，只在轮到该座位时清理其上一手。"""
        del table_players, passed_players
        return self.session.table_display_actions()

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
        result = self.session.play_human_cards(sel)
        if result.ok:
            self._hand_selected_indices.clear()
            self._refresh_all()
            self.set_timer(0.3, self._maybe_ai_turn)
        else:
            self.sub_title = result.message
            self._refresh_all()

    def action_pass(self) -> None:
        s = self._state()
        if s.finished or s.turn_index != self.human:
            return
        result = self.session.pass_human()
        if result.ok:
            self._refresh_all()
            self.set_timer(0.3, self._maybe_ai_turn)
        else:
            self.sub_title = result.message
            self._refresh_all()

    def action_hint(self) -> None:
        s = self._state()
        if s.finished or s.turn_index != self.human:
            return
        result = self.session.hint_for_human()
        self.sub_title = result.message
        self._refresh_all()

    def action_claim(self) -> None:
        from ...engine.state import claim

        s = self._state()
        try:
            claim(s, self.human, len(s.hands[self.human]))
        except IllegalPlayError as e:
            self.sub_title = f"报牌由系统自动执行：{e}"
            self._last_action = f"报牌由系统自动执行：{e}"
            self._refresh_all()
            return
        self.sub_title = f"你报了 {len(s.hands[self.human])} 张"
        self._last_action = f"你报牌：{len(s.hands[self.human])} 张"
        self._refresh_all()

    def action_next_game(self) -> None:
        result = self.session.start_next_game()
        if not result.ok:
            self._refresh_all()
            return
        self._hand_selected_indices.clear()
        self._hand_cursor = 0
        self._refresh_all()
        self.set_timer(0.3, self._maybe_ai_turn)

    def action_rules(self) -> None:
        from .rule import RuleScreen

        self.app.push_screen(RuleScreen())

    def action_back(self) -> None:
        s = self._state()
        try:
            if s.finished:
                self.session.save_finished_if_needed()
            else:
                self.session.save_unfinished()
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
            self.session.save_finished_if_needed()
            return
        ai_action_limit = 12
        ai_actions = self.session.run_ai_until_human(limit=ai_action_limit)
        if ai_actions:
            self._last_action = "；".join(ai_actions[-4:])
        self._refresh_all()
        s = self._state()
        if (
            not s.finished
            and s.turn_index != self.human
            and len(ai_actions) >= ai_action_limit
        ):
            self.set_timer(0.1, self._maybe_ai_turn)
        if s.finished:
            self.session.save_finished_if_needed()

    def _describe_ai_action(self, state: GameState, player: int, history_len_before: int) -> str:
        del state
        return self.session.describe_player_action(player, history_len_before)

    def _save_game_result(self) -> None:
        """保存游戏结果（历史和统计）。"""
        self.session.save_finished_if_needed()
        if self._last_action.startswith("保存失败："):
            self.sub_title = self._last_action

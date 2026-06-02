"""GameState：游戏对局的当前状态。

设计：可变 dataclass，所有 mutation 通过方法，便于"回放事件 → 重放状态"。

State 组成：
- level: 当前级牌点数（2..14，A=14）
- wild_card: 逢人配（红心级牌）
- hands: 4 家手牌（list of list[Card]）
- turn_index: 当前轮到的玩家
- table: 本轮出牌区（按出牌顺序）
- pass_count: 本轮已过牌数
- leader: 本轮的先出者
- history: 已发生的事件
- finish_order: 已出完牌的玩家顺序（空表示未结束）
- bomb_count: 各队本局已出炸弹数
- has_played_ace: 各队本局是否出过 A
- finished: 是否结束
- tribute_state: 进贡/还贡阶段的状态
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from .card import (
    Card,
    RANK_2,
    RANK_A,
    RANK_BIG_JOKER,
    RANK_SMALL_JOKER,
    Suit,
)
from .deck import deal, make_deck, shuffle_deck
from .events import Event, ShuffleDeal
from .hand import Hand, Pattern


# 队伍：0=东-西（player 0 & 2），1=南-北（player 1 & 3）
def team_of(player: int) -> int:
    return player % 2


# 座位名
SEAT_NAMES = ["东", "南", "西", "北"]


@dataclass
class TributeState:
    """进贡/还贡阶段状态。"""

    pending: bool = False  # 是否在进贡/还贡阶段
    from_player: int = -1  # 进贡方
    to_player: int = -1  # 收贡方
    tribute_card: Optional[Card] = None  # 已进贡的牌（待还贡时使用）
    resisted: bool = False  # 是否抗贡


@dataclass
class GameState:
    """一局掼蛋的完整状态。"""

    level: int
    wild_card: Optional[Card]
    hands: list[list[Card]]  # 4 家手牌
    turn_index: int  # 0-3
    table: list[Pattern] = field(default_factory=list)
    pass_count: int = 0
    leader: Optional[int] = None  # 本轮先手
    history: list[Event] = field(default_factory=list)
    finish_order: list[int] = field(default_factory=list)
    team_bomb_count: list[int] = field(default_factory=lambda: [0, 0])
    has_played_ace: list[bool] = field(default_factory=lambda: [False, False])
    finished: bool = False
    tribute_state: TributeState = field(default_factory=TributeState)
    drift: bool = False
    trick_number: int = 0  # 第几轮（一轮 = 一手出牌 + 后续过牌/压牌）
    next_trick_starter: Optional[int] = None  # 下一轮的先手

    def hand(self, player: int) -> list[Card]:
        return self.hands[player]

    def hand_size(self, player: int) -> int:
        return len(self.hands[player])

    def is_finished(self) -> bool:
        return self.finished

    def current_player(self) -> int:
        return self.turn_index

    def to_wild_card(self) -> Optional[Card]:
        """返回本局的逢人配。"""
        return self.wild_card


# ---- 玩家行动 ----


class IllegalPlayError(Exception):
    """出牌不合法。"""


def play_pattern(state: GameState, player: int, pattern: Pattern) -> None:
    """玩家 player 出牌 pattern。

    必须满足：
    - player == state.turn_index
    - pattern.cards 全部在 player 手牌中
    - 当前 table 为空（新一轮先手）或 pattern 可压 table[-1]
    - 玩家未在该轮过牌
    """
    if state.finished:
        raise IllegalPlayError("game is finished")
    if player != state.turn_index:
        raise IllegalPlayError(f"not player's turn: {player} != {state.turn_index}")

    # 验证 pattern 的牌都在手牌中
    hand = state.hands[player]
    for c in pattern.cards:
        if c not in hand:
            raise IllegalPlayError(f"card {c} not in hand")

    # 验证可压当前 table[-1]（若有）
    if state.table and pattern.can_be_played_on(state.table[-1]) is False:
        raise IllegalPlayError(
            f"pattern {pattern} cannot beat {state.table[-1]}"
        )

    # 出牌：从手牌中删除
    for c in pattern.cards:
        hand.remove(c)

    # 更新 table
    state.table.append(pattern)

    # 记录事件
    from .events import TurnPlayed

    state.history.append(
        TurnPlayed(
            player=player,
            pattern=pattern,
            hand_remaining=len(hand),
        )
    )

    # 更新本轮 leader
    if state.leader is None:
        state.leader = player
    state.pass_count = 0

    # 累计本队炸弹数
    from .hand import PatternType

    if pattern.type == PatternType.BOMB:
        state.team_bomb_count[team_of(player)] += 1
    # 记录出 A
    if pattern.type == PatternType.SINGLE and any(
        c.rank == RANK_A and not c.is_joker for c in pattern.cards
    ):
        state.has_played_ace[team_of(player)] = True

    # 检查是否出完
    if not hand:
        if player not in state.finish_order:
            state.finish_order.append(player)
        # 上游产生：游戏结束（剩余玩家按手牌数排中游/末游）
        _finish_game(state)
        return

    # 推进到下一个玩家
    state.turn_index = _next_player(state, player)


def pass_turn(state: GameState, player: int) -> None:
    """玩家过牌。"""
    if state.finished:
        raise IllegalPlayError("game is finished")
    if player != state.turn_index:
        raise IllegalPlayError(f"not player's turn: {player} != {state.turn_index}")
    if not state.table:
        # 你是新一轮的先手，不能过牌
        raise IllegalPlayError("leader cannot pass")

    from .events import Pass as PassEvent

    state.history.append(
        PassEvent(player=player, hand_remaining=len(state.hands[player]))
    )

    state.pass_count += 1

    # 检查本轮是否结束
    # 一轮内"全过"或"全炸完"后，最后一个出牌者获得下一轮先手
    if state.pass_count >= 3:
        # 3 个非 leader 都过了 → 本轮结束
        # leader 是最后一个出牌的人 → 下一轮先手
        _end_trick(state, last_player=state.leader)
        return

    state.turn_index = _next_player(state, player)


def claim(state: GameState, player: int, count: int) -> None:
    """报牌。"""
    from .events import Claim as ClaimEvent

    state.history.append(ClaimEvent(player=player, count=count))


# ---- 内部工具 ----


def _next_player(state: GameState, current: int) -> int:
    """下一个玩家（按逆时针）。"""
    return (current + 1) % 4


def _end_trick(state: GameState, last_player: Optional[int]) -> None:
    """结束当前轮，开新轮。"""
    state.table = []
    state.pass_count = 0
    state.leader = last_player
    state.trick_number += 1
    state.next_trick_starter = last_player
    if last_player is not None:
        state.turn_index = last_player


def _finish_game(state: GameState) -> None:
    """结束一局。计算升级、漂牌、过 A。"""
    state.finished = True

    # 找出尚未 finish_order 的玩家，按当前手牌数排
    remaining = [p for p in range(4) if p not in state.finish_order]
    # 简化：手牌多者排后面
    remaining.sort(key=lambda p: -len(state.hands[p]))
    full_order = list(state.finish_order) + remaining

    # 计算升级
    from .rules.scoring import compute_level_change

    team_levels = [state.level, state.level]  # 简化：双方起始级牌相同
    delta_team0, delta_team1 = compute_level_change(
        state.finish_order, state.team_bomb_count
    )
    new_level_0 = min(RANK_A, max(RANK_2, state.level + delta_team0))
    new_level_1 = min(RANK_A, max(RANK_2, state.level + delta_team1))
    new_levels = [new_level_0, new_level_1]

    # 漂牌检查：上游方最后一手为 5 张+级牌炸弹
    from .hand import PatternType

    drift = False
    if state.history:
        last = state.history[-1]
        if (
            isinstance(last, TurnPlayed)
            and state.finish_order
            and last.player == state.finish_order[0]
            and last.pattern.type == PatternType.BOMB
            and last.pattern.length >= 5
            and all(c.rank == state.level for c in last.pattern.cards)
        ):
            drift = True
            state.drift = True
            # 漂牌：上游队额外 +3
            upstream_team = team_of(state.finish_order[0])
            new_levels[upstream_team] = min(
                RANK_A, new_levels[upstream_team] + 3
            )

    # 过 A：升到 A 后下一局为 2，再升即过 A
    # 简化：单局结束后，若上游队级牌 = A，标记 guo_a_candidate
    guo_a = False
    if new_levels[0] > RANK_A or new_levels[1] > RANK_A:
        guo_a = True
        new_levels[0] = RANK_2  # 强制回到 2
        new_levels[1] = RANK_2

    state.team_levels_final = new_levels  # type: ignore[attr-defined]
    state.drift_flag = drift  # type: ignore[attr-defined]
    state.guo_a = guo_a  # type: ignore[attr-defined]

    from .events import GameOver, LevelUp

    if not guo_a:
        if delta_team0 > 0:
            state.history.append(
                LevelUp(team=0, new_level=new_levels[0], delta=delta_team0)
            )
        if delta_team1 > 0:
            state.history.append(
                LevelUp(team=1, new_level=new_levels[1], delta=delta_team1)
            )
    state.history.append(
        GameOver(
            finish_order=tuple(full_order),
            team_levels=tuple(new_levels),
            drift=drift,
            guo_a=guo_a,
        )
    )


# ---- 暴露给 events 模块的 TurnPlayed（避免循环导入）----
from .events import TurnPlayed  # noqa: E402


def make_initial_state(
    level: int = 2,
    first_player: int = 0,
    seed: Optional[int] = None,
) -> GameState:
    """构造一局的初始状态（发牌完毕）。

    Args:
        level: 本局级牌点数（2..14）
        first_player: 首发起家索引
        seed: 随机种子（用于复现）
    """
    if not RANK_2 <= level <= RANK_A:
        raise ValueError(f"level must be 2..14, got {level}")

    rng = random.Random(seed)
    deck = make_deck()
    shuffled = shuffle_deck(deck, rng)
    hands = deal(shuffled, 4)

    # 确定 wild_card：红心级牌
    wild_card: Optional[Card] = None
    for p in (0, 1, 2, 3):
        for c in hands[p]:
            if c.rank == level and c.suit == Suit.HEARTS:
                wild_card = c
                break
        if wild_card is not None:
            break

    state = GameState(
        level=level,
        wild_card=wild_card,
        hands=hands,
        turn_index=first_player,
        leader=first_player,
    )
    # 记录发牌事件
    state.history.append(
        ShuffleDeal(
            level=level,
            wild_card=wild_card,
            hand_sizes=tuple(len(h) for h in hands),
            first_player=first_player,
            seed=seed if seed is not None else 0,
        )
    )
    return state


def sort_hand_cards(cards: list[Card]) -> list[Card]:
    """按从大到小排序。"""
    return sorted(cards, reverse=True)


def remove_cards_from_hand(hand: list[Card], cards_to_remove: list[Card]) -> None:
    """从手牌中删除 cards_to_remove（按内容匹配，不按位置）。"""
    for c in cards_to_remove:
        try:
            hand.remove(c)
        except ValueError:
            raise ValueError(f"card {c} not in hand")

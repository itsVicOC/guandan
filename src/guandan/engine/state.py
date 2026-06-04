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


def partner_of(player: int) -> int:
    """对家（队友）。座位按 东=0 南=1 西=2 北=3，对家 = (p+2) % 4。

    例如：partner_of(0) == 2（西是东的对家），partner_of(1) == 3（北是南的对家）。
    """
    return (player + 2) % 4


def is_teammate(a: int, b: int) -> bool:
    """a 和 b 是否同队。"""
    return team_of(a) == team_of(b)


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
        # 3rd finisher 产生时游戏结束（剩 1 人即末游）
        if len(state.finish_order) == 3:
            _finish_game(state)
            return
        # 1st / 2nd finisher：不立即触发接风，要等其他 3 人是否压牌
        # 让 turn 继续推进，下家可以选择压牌或过牌
        state.turn_index = _next_player(state, player)
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

    # 检查本轮是否结束：所有"能行动的非 leader 玩家"都过了
    if state.pass_count >= _active_non_leader_count(state):
        _end_trick_or_jiefeng(state)
        return

    state.turn_index = _next_player(state, player)


def claim(state: GameState, player: int, count: int) -> None:
    """报牌。"""
    from .events import Claim as ClaimEvent

    state.history.append(ClaimEvent(player=player, count=count))


# ---- 内部工具 ----


def _next_player(state: GameState, current: int) -> int:
    """下一个玩家（按逆时针），跳过已出完手牌的玩家。"""
    nxt = (current + 1) % 4
    visited = 0
    while nxt in state.finish_order:
        nxt = (nxt + 1) % 4
        visited += 1
        if visited >= 4:
            # 全部出完（理论上不该走到这里，因为 3rd 出完时会结束游戏）
            return current
    return nxt


def _active_non_leader_count(state: GameState) -> int:
    """当前轮中"能行动的非 leader 玩家"数量（未出完手牌）。

    用于判断本轮是否结束：当 pass_count >= 此值时，触发 _end_trick_or_jiefeng。
    例如：
    - 4 人都未出完：非 leader = 3
    - leader 出完、1 个非 leader 也出完：非 leader = 2
    - leader 出完、2 个非 leader 也出完：非 leader = 1
    """
    leader = state.leader
    n = 0
    for p in range(4):
        if p != leader and p not in state.finish_order:
            n += 1
    return n


def _end_trick_or_jiefeng(state: GameState) -> None:
    """所有"能行动的非 leader 玩家"都过牌后调用。

    规则（按文档）：
    - 若当前 leader 已出完手牌 → 触发接风：
      - 新的 leader = leader 的对家（如果对家未出完手牌）
      - 如果对家也已出完（如头游+二游同队的极端情况）→ 找下一个未出完的玩家
    - 若当前 leader 还在玩 → 正常开新轮，leader 继续
    - 清空 table、重置 pass_count
    """
    last_leader = state.leader
    state.table = []
    state.pass_count = 0
    state.trick_number += 1

    if last_leader is not None and last_leader in state.finish_order:
        # 触发接风：对家成为新 leader
        partner = partner_of(last_leader)
        if partner not in state.finish_order:
            new_leader = partner
        else:
            # 对家也出完了（如头游+二游同队），找下一个 active 玩家
            new_leader = (last_leader + 1) % 4
            while new_leader in state.finish_order:
                new_leader = (new_leader + 1) % 4
                if new_leader == last_leader:
                    return  # 全部出完（不该发生）
    else:
        new_leader = last_leader

    state.leader = new_leader
    state.next_trick_starter = new_leader
    if new_leader is not None:
        state.turn_index = new_leader


def _finish_game(state: GameState) -> None:
    """结束一局。计算升级、漂牌、过 A。

    文档规则：
    - 3rd finisher 产生时结束游戏，剩 1 人为末游
    - 升级：头游+二游=+3, 头游+三游=+2, 头游+末游=+1
    - 对方不降级
    - 漂牌：上游最后一手为 5+ 张级牌炸弹 → 额外 +3
    - 过 A：必须"双上"（头游方队友非末游）才算成功
    """
    state.finished = True

    # finish_order = [头游, 二游, 三游]，剩 1 人是末游
    if len(state.finish_order) != 3:
        # 异常：理论上不该走到这里
        return
    head = state.finish_order[0]
    second = state.finish_order[1]
    third = state.finish_order[2]
    last = [p for p in range(4) if p not in state.finish_order][0]
    full_order = [head, second, third, last]

    # 升级：按头游方的两个名次组合
    from .rules.scoring import compute_level_change

    delta_team0, delta_team1 = compute_level_change(
        head, second, third, last, state.team_bomb_count
    )
    new_level_0 = min(RANK_A, max(RANK_2, state.level + delta_team0))
    new_level_1 = min(RANK_A, max(RANK_2, state.level + delta_team1))
    new_levels = [new_level_0, new_level_1]

    # 漂牌检查
    from .hand import PatternType

    drift = False
    if state.history:
        for ev in reversed(state.history):
            if isinstance(ev, TurnPlayed) and ev.player == head:
                p = ev.pattern
                if (
                    p.type == PatternType.BOMB
                    and p.length >= 5
                    and all(c.rank == state.level for c in p.cards)
                ):
                    drift = True
                    state.drift = True
                break
        if drift:
            upstream_team = team_of(head)
            new_levels[upstream_team] = min(RANK_A, new_levels[upstream_team] + 3)

    # 过 A 判定：头游方 + 队友非末游（= 头游+二游 或 头游+三游）
    # 当前局打到 A 才能"冲 A"
    # 升级前的级牌是 state.level
    guo_a = False
    guo_a_failed = False
    upstream_team = team_of(head)
    upstream_partner_rank = (
        2 if (second == partner_of(head)) else (3 if (third == partner_of(head)) else 4)
    )
    if state.level == RANK_A:
        if upstream_partner_rank in (2, 3):
            # 队友是 2nd 或 3rd → 双上 → 过 A 成功
            guo_a = True
            new_levels[upstream_team] = RANK_2  # 过 A 后回到 2
            # 另一队不降级
        else:
            # 队友是末游 → 冲 A 失败
            guo_a_failed = True
            # 文档说"退回级牌2重打或重新打A"
            # 我们这里简化为：上游方降回 2
            new_levels[upstream_team] = RANK_2
            # 另一方不变

    state.team_levels_final = new_levels  # type: ignore[attr-defined]
    state.drift_flag = drift  # type: ignore[attr-defined]
    state.guo_a = guo_a  # type: ignore[attr-defined]
    state.guo_a_failed = guo_a_failed  # type: ignore[attr-defined]

    from .events import GameOver, LevelUp

    # 即使过 A 成功或失败也记录 LevelUp（用于显示）
    if delta_team0 != 0 or guo_a or guo_a_failed:
        state.history.append(
            LevelUp(
                team=0,
                new_level=new_levels[0],
                delta=new_levels[0] - state.level,
            )
        )
    if delta_team1 != 0 or guo_a or guo_a_failed:
        state.history.append(
            LevelUp(
                team=1,
                new_level=new_levels[1],
                delta=new_levels[1] - state.level,
            )
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

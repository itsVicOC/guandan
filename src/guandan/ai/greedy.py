"""贪心出牌选择：找"刚好压过桌顶的最小牌型"。

复刻自 `cli._greedy_ai_select` 的核心算法，清理为可被多档策略共享的纯函数。

设计：枚举有结构的牌型子集（单/对/三/炸弹），按"刚好 > 桌顶"的最小牌型返回。
**不做**指数级 hand 子集枚举——这足够对付 M2 三个档位的需求。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..engine.card import (
    Card,
    RANK_2,
    RANK_A,
    RANK_BIG_JOKER,
    RANK_SMALL_JOKER,
)
from ..engine.hand import Pattern, PatternType, sort_cards
from ..engine.rules.patterns import find_complete_pattern
from ..engine.state import GameState


def _group_by_rank(hand: List[Card]) -> Dict[int, List[Card]]:
    by_rank: Dict[int, List[Card]] = {}
    for c in hand:
        by_rank.setdefault(c.rank, []).append(c)
    return by_rank


def _count_wild(hand: List[Card], wild: Optional[Card]) -> int:
    if wild is None:
        return 0
    return sum(1 for c in hand if c == wild)


def _smallest_single_above(hand: List[Card], target: int, wild: Optional[Card]) -> Optional[Pattern]:
    """找最小单张 rank > target。wild 不参与单张（避免浪费万能牌）。"""
    for c in reversed(sort_cards(hand)):
        if c.rank <= target:
            return None
        if c == wild:
            continue
        p = find_complete_pattern([c], wild)
        if p and p.type == PatternType.SINGLE:
            return p
    return None


def _smallest_pair_above(hand: List[Card], by_rank: Dict[int, List[Card]], target: int, wild: Optional[Card], wild_count: int) -> Optional[Pattern]:
    """找最小对子 rank > target。"""
    for r in range(target + 1, RANK_A + 1):
        if r == RANK_SMALL_JOKER or r == RANK_BIG_JOKER:
            continue
        cards = by_rank.get(r, [])
        if len(cards) >= 2:
            p = find_complete_pattern(cards[:2], wild)
            if p:
                return p
    # 用 wild 凑对
    if wild_count >= 1:
        for r in range(target + 1, RANK_A + 1):
            cards = by_rank.get(r, [])
            if len(cards) >= 1 and r not in (RANK_SMALL_JOKER, RANK_BIG_JOKER):
                p = find_complete_pattern([cards[0], wild], wild)
                if p and p.type == PatternType.PAIR:
                    return p
    return None


def _smallest_triple_above(hand: List[Card], by_rank: Dict[int, List[Card]], target: int, wild: Optional[Card], wild_count: int) -> Optional[Pattern]:
    """找最小三张 rank > target。"""
    for r in range(target + 1, RANK_A + 1):
        if r == RANK_SMALL_JOKER or r == RANK_BIG_JOKER:
            continue
        cards = by_rank.get(r, [])
        if len(cards) >= 3:
            p = find_complete_pattern(cards[:3], wild)
            if p:
                return p
    if wild_count >= 1:
        for r in range(target + 1, RANK_A + 1):
            cards = by_rank.get(r, [])
            if len(cards) >= 2 and r not in (RANK_SMALL_JOKER, RANK_BIG_JOKER):
                p = find_complete_pattern(cards[:2] + [wild], wild)
                if p and p.type == PatternType.TRIPLE:
                    return p
    return None


def _smallest_bomb(hand: List[Card], by_rank: Dict[int, List[Card]], table_top: Pattern, wild: Optional[Card], wild_count: int) -> Optional[Pattern]:
    """找能压桌顶的最小炸弹（BOMB / STRAIGHT_FLUSH / FOUR_JOKERS）。"""
    # 普通 4+ 张炸弹（按 rank 从小到大，找到第一个可压的）
    for r in range(RANK_2, RANK_A + 1):
        cards = by_rank.get(r, [])
        if len(cards) >= 4:
            length = min(len(cards), 8)
            p = find_complete_pattern(cards[:length], wild)
            if p and p.type == PatternType.BOMB and p.can_be_played_on(table_top):
                return p
    # wild 凑炸弹
    if wild is not None and wild_count >= 1:
        for r in range(RANK_2, RANK_A + 1):
            cards = by_rank.get(r, [])
            need = 4 - wild_count
            if 0 < need <= len(cards) and r not in (RANK_SMALL_JOKER, RANK_BIG_JOKER):
                p = find_complete_pattern(cards[:need] + [wild] * wild_count, wild)
                if p and p.type == PatternType.BOMB and p.can_be_played_on(table_top):
                    return p
    # 四王
    jokers = [c for c in hand if c.is_joker]
    big = sum(1 for c in jokers if c.is_big_joker)
    small = sum(1 for c in jokers if c.is_small_joker)
    if big >= 2 and small >= 2:
        p = find_complete_pattern(jokers[:4], wild)
        if p and p.type == PatternType.FOUR_JOKERS:
            return p
    return None


def _lead_smallest(hand: List[Card], wild: Optional[Card]) -> Optional[Pattern]:
    """新一轮先手：出最小单张（不用 wild）。"""
    for c in reversed(sort_cards(hand)):
        if c == wild:
            continue
        p = find_complete_pattern([c], wild)
        if p and p.type == PatternType.SINGLE:
            return p
    # 手牌里只有 wild？出 wild 当单张
    if hand:
        p = find_complete_pattern([hand[0]], wild)
        if p:
            return p
    return None


def select_min_winning(state: GameState, player: int) -> Optional[Pattern]:
    """为 player 找最小可压牌型。

    行为：
    - table 空（leader）→ 出最小单张
    - table 顶是 SINGLE → 找最小可压单张
    - table 顶是 PAIR / TRIPLE → 找最小可压同型
    - 找不到同型 → 找最小炸弹
    - 其他牌型（顺子等）→ 直接跳到炸弹
    """
    hand = state.hands[player]
    if not hand:
        return None

    wild = state.wild_card
    table_top = state.table[-1] if state.table else None

    if table_top is None:
        return _lead_smallest(hand, wild)

    by_rank = _group_by_rank(hand)
    wild_count = _count_wild(hand, wild)

    if table_top.type == PatternType.SINGLE:
        p = _smallest_single_above(hand, table_top.rank, wild)
        if p:
            return p
    elif table_top.type == PatternType.PAIR:
        p = _smallest_pair_above(hand, by_rank, table_top.rank, wild, wild_count)
        if p:
            return p
    elif table_top.type == PatternType.TRIPLE:
        p = _smallest_triple_above(hand, by_rank, table_top.rank, wild, wild_count)
        if p:
            return p
    # 其他牌型（顺子/连对/钢板/三带二）：贪心暂不处理 → 直接找炸弹

    return _smallest_bomb(hand, by_rank, table_top, wild, wild_count)

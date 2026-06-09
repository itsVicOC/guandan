"""手牌价值评估。档 1+ 用来在多个候选出牌中选"损失最小"的那手。

启发式（不是精确期望值）：
- 出牌本身的牌型类别越大（`Pattern.weight`），出牌越"贵"
- 拆散高对子比拆散单张更贵
- 用 逢人配 出小牌 = 大亏
- 炸弹 / 同花顺 / 四王非常贵，除非能确认收掉这一轮

返回 float，越小越划算。
"""
from __future__ import annotations

from collections import Counter
from typing import List, Optional

from ..engine.card import (
    RANK_A,
    RANK_BIG_JOKER,
    RANK_SMALL_JOKER,
)
from ..engine.hand import Pattern, PatternType, effective_rank
from ..engine.rules.patterns import find_complete_pattern
from ..engine.state import GameState


def _hand_breakdown(cards: list) -> dict:
    """按 rank 统计张数。"""
    d: dict = {}
    for c in cards:
        d[c.rank] = d.get(c.rank, 0) + 1
    return d


def _is_bomb(t: PatternType) -> bool:
    return t in (PatternType.BOMB, PatternType.STRAIGHT_FLUSH, PatternType.FOUR_JOKERS)


def _count_wild_in_pattern(p: Pattern, wild: Optional[object]) -> int:
    if wild is None:
        return 0
    return sum(1 for c in p.cards if c == wild)


def estimate_pattern_cost(
    state: GameState,
    player: int,
    pattern: Pattern,
) -> float:
    """评估"出这手牌"对 player 手力的损失。

    越小越划算。档 1+ 在多个候选牌型中选 `cost` 最小者。
    """
    hand = state.hands[player]
    wild = state.wild_card

    # 拆分手牌 → 出牌后剩余手牌（用 multiset 避免误删）
    pat_counts = Counter(pattern.cards)
    rem_counts: Counter = Counter(hand)
    rem_counts.subtract(pat_counts)
    rem_cards = list(rem_counts.elements())

    breakdown_before = _hand_breakdown(hand)
    breakdown_after = _hand_breakdown(rem_cards)

    # ---- 1. 牌型类别基础成本 ----
    base = float(pattern.weight)

    # ---- 2. 拆对子 / 拆三张惩罚 ----
    # before=2 → after=1 是"拆对"；before=3 → after=2 是"拆三张"
    breakup = 0.0
    for r, cnt_after in breakdown_after.items():
        cnt_before = breakdown_before.get(r, 0)
        if cnt_before >= 2 and cnt_after == 1:
            breakup += 3.0
        elif cnt_before >= 3 and cnt_after == 2:
            breakup += 5.0

    # ---- 3. 浪费 逢人配 ----
    wild_used = _count_wild_in_pattern(pattern, wild)
    wild_penalty = wild_used * 8.0

    # ---- 4. 拆王 / 拆级牌的小加成 ----
    high_penalty = 0.0
    for c in pattern.cards:
        if c.is_big_joker:
            high_penalty += 4.0
        elif c.is_small_joker:
            high_penalty += 3.0
        elif c.rank == RANK_A:
            high_penalty += 1.5
        elif c.rank == 13:  # K
            high_penalty += 0.5

    # ---- 5. 炸弹特别贵 ----
    bomb_premium = 0.0
    if _is_bomb(pattern.type):
        bomb_premium = 5.0
        if pattern.type == PatternType.STRAIGHT_FLUSH:
            bomb_premium += 3.0
        elif pattern.type == PatternType.FOUR_JOKERS:
            bomb_premium += 6.0

    # ---- 6. 收牌奖励：出完手牌 → 估值大幅降低 ----
    finish_bonus = 0.0
    if len(rem_cards) == 0:
        finish_bonus = -20.0

    return base + breakup + wild_penalty + high_penalty + bomb_premium + finish_bonus


def enumerate_candidate_plays(
    state: GameState,
    player: int,
    *,
    max_candidates: int = 8,
) -> List[Pattern]:
    """生成 top-N 候选出牌，按 `estimate_pattern_cost` 升序。

    M2 策略层用：在多个"能压"的牌型里选估值最低的。

    实现：
    1. 枚举手牌里能压的所有同型牌型 + 最小炸弹
    2. 按 `estimate_pattern_cost` 排序
    3. 截断到 `max_candidates`
    """
    from .greedy import (
        _count_wild,
        _group_by_rank,
        _normal_ranks_above,
        _smallest_bomb,
    )

    hand = state.hands[player]
    if not hand:
        return []
    wild = state.wild_card
    table_top = state.table[-1] if state.table else None
    by_rank = _group_by_rank(hand)
    wild_count = _count_wild(hand, wild)

    candidates: List[Pattern] = []

    if table_top is None:
        # leader 模式：所有非 wild 单张都是候选
        for c in hand:
            if c == wild:
                continue
            p = find_complete_pattern([c], wild)
            if p and p.type == PatternType.SINGLE:
                candidates.append(p)
    else:
        if table_top.type == PatternType.SINGLE:
            for c in hand:
                if c == wild:
                    continue
                if effective_rank(c.rank, state.level) > effective_rank(
                    table_top.rank, state.level
                ):
                    p = find_complete_pattern([c], wild)
                    if p and p.type == PatternType.SINGLE:
                        candidates.append(p)
        elif table_top.type == PatternType.PAIR:
            for r in _normal_ranks_above(table_top.rank, state.level):
                if r in (RANK_SMALL_JOKER, RANK_BIG_JOKER):
                    continue
                cards = by_rank.get(r, [])
                if len(cards) >= 2:
                    p = find_complete_pattern(cards[:2], wild)
                    if p:
                        candidates.append(p)
            if wild is not None and wild_count >= 1:
                for r in _normal_ranks_above(table_top.rank, state.level):
                    cards = by_rank.get(r, [])
                    if len(cards) >= 1 and r not in (RANK_SMALL_JOKER, RANK_BIG_JOKER):
                        p = find_complete_pattern([cards[0], wild], wild)
                        if p and p.type == PatternType.PAIR:
                            candidates.append(p)
        elif table_top.type == PatternType.TRIPLE:
            for r in _normal_ranks_above(table_top.rank, state.level):
                if r in (RANK_SMALL_JOKER, RANK_BIG_JOKER):
                    continue
                cards = by_rank.get(r, [])
                if len(cards) >= 3:
                    p = find_complete_pattern(cards[:3], wild)
                    if p:
                        candidates.append(p)

        # 炸弹独立候选
        bomb = _smallest_bomb(hand, by_rank, table_top, wild, wild_count, state.level)
        if bomb:
            candidates.append(bomb)

    # 去重
    seen: set = set()
    unique: List[Pattern] = []
    for p in candidates:
        key = (p.type, p.rank, p.length, p.wild_used, p.suit)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    unique.sort(key=lambda p: estimate_pattern_cost(state, player, p))
    return unique[:max_candidates]

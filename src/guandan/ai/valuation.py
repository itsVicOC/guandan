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

from ..engine.card import RANK_A, Card
from ..engine.hand import Pattern, PatternType, effective_rank
from ..engine.rules.patterns import detect_patterns
from ..engine.state import GameState
from .candidates import enumerate_legal_patterns
from .context import opponent_min_cards as context_opponent_min_cards


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


_STRUCTURE_TYPES = {
    PatternType.STRAIGHT,
    PatternType.PAIR_SEQUENCE,
    PatternType.TRIPLE_SEQUENCE,
    PatternType.TRIPLE_PAIR,
}

_CardKey = tuple[tuple[int, int, int], ...]
_StructureCache = dict[_CardKey, float]


def _cards_key(cards: list[Card]) -> _CardKey:
    counts = Counter(cards)
    return tuple(
        sorted((card.rank, int(card.suit), count) for card, count in counts.items())
    )


def _best_structure_score(cards: list, wild: Optional[Card]) -> float:
    """估算手牌中顺子/连对/钢板/三带二的保留价值。"""
    best = 0.0
    for p in detect_patterns(cards, wild):
        if p.type not in _STRUCTURE_TYPES:
            continue
        score = float(len(p.cards) + p.weight) - p.wild_used * 0.5
        if score > best:
            best = score
    return best


def _cached_structure_score(
    cards: list[Card],
    wild: Optional[Card],
    cache: Optional[_StructureCache],
) -> float:
    if cache is None:
        return _best_structure_score(cards, wild)
    key = _cards_key(cards)
    if key not in cache:
        cache[key] = _best_structure_score(cards, wild)
    return cache[key]


def estimate_pattern_cost(
    state: GameState,
    player: int,
    pattern: Pattern,
) -> float:
    """评估"出这手牌"对 player 手力的损失。

    越小越划算。档 1+ 在多个候选牌型中选 `cost` 最小者。
    """
    return _estimate_pattern_cost(state, player, pattern)


def _estimate_pattern_cost(
    state: GameState,
    player: int,
    pattern: Pattern,
    *,
    before_structure: Optional[float] = None,
    structure_cache: Optional[_StructureCache] = None,
    opponent_min_cards: Optional[int] = None,
) -> float:
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

    # ---- 4. 拆王 / 拆级牌 / 拆高牌的小加成 ----
    high_penalty = 0.0
    for c in pattern.cards:
        if c.is_big_joker:
            high_penalty += 4.0
        elif c.is_small_joker:
            high_penalty += 3.0
        elif c != wild and effective_rank(c.rank, state.level) > RANK_A:
            high_penalty += 2.5
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

    # ---- 6. 保留顺子/连对/钢板等结构 ----
    structure_penalty = 0.0
    if pattern.type not in _STRUCTURE_TYPES and not _is_bomb(pattern.type):
        before_score = (
            _cached_structure_score(hand, wild, structure_cache)
            if before_structure is None
            else before_structure
        )
        after_structure = _cached_structure_score(rem_cards, wild, structure_cache)
        structure_penalty = max(0.0, before_score - after_structure) * 0.8

    # ---- 7. 收牌奖励：出完手牌 → 估值大幅降低 ----
    finish_bonus = 0.0
    if len(rem_cards) == 0:
        finish_bonus = -20.0

    # ---- 8. 领牌整理：自然结构牌能显著减少手牌轮次 ----
    lead_shedding_bonus = 0.0
    if not state.table and pattern.type in _STRUCTURE_TYPES and not _is_bomb(pattern.type):
        lead_shedding_bonus = -min(8.0, len(pattern.cards) * 1.3)

    # ---- 9. 对手报单时避免用单张领牌 ----
    single_lead_pressure = 0.0
    if (
        not state.table
        and pattern.type == PatternType.SINGLE
        and (
            opponent_min_cards
            if opponent_min_cards is not None
            else context_opponent_min_cards(state, player)
        )
        == 1
    ):
        single_lead_pressure = 6.0

    return (
        base
        + breakup
        + wild_penalty
        + high_penalty
        + bomb_premium
        + structure_penalty
        + finish_bonus
        + lead_shedding_bonus
        + single_lead_pressure
    )


def enumerate_candidate_plays(
    state: GameState,
    player: int,
    *,
    max_candidates: int = 8,
) -> List[Pattern]:
    """生成 top-N 候选出牌，按 `estimate_pattern_cost` 升序。

    M2 策略层用：在多个"能压"的牌型里选估值最低的。

    实现：
    1. 用规则引擎枚举当前所有合法候选
    2. 按 `estimate_pattern_cost` 排序
    3. 截断到 `max_candidates`
    """
    hand = state.hands[player]
    if not hand:
        return []
    candidates = enumerate_legal_patterns(state, player)
    structure_cache: _StructureCache = {}
    before_structure = _cached_structure_score(hand, state.wild_card, structure_cache)
    min_opponent_cards = context_opponent_min_cards(state, player) if not state.table else 0
    candidates.sort(
        key=lambda p: _estimate_pattern_cost(
            state,
            player,
            p,
            before_structure=before_structure,
            structure_cache=structure_cache,
            opponent_min_cards=min_opponent_cards,
        )
    )
    return candidates[:max_candidates]

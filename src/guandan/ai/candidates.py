"""AI 候选出牌生成。

AI 不再手写各牌型枚举，而是复用规则层的 `detect_patterns()`：
先从当前手牌识别所有可出的牌型，再按桌顶牌过滤合法回应。
"""
from __future__ import annotations

from collections import Counter
from typing import List, Optional

from ..engine.card import Card
from ..engine.hand import Pattern, comparison_rank
from ..engine.rules.comparator import bomb_strength, is_bomb_type
from ..engine.rules.patterns import detect_patterns
from ..engine.state import GameState


def _card_counter_key(cards: tuple[Card, ...]) -> tuple[tuple[int, int, int], ...]:
    counts = Counter(cards)
    return tuple(
        sorted((card.rank, int(card.suit), count) for card, count in counts.items())
    )


def _pattern_key(pattern: Pattern) -> tuple:
    return (
        pattern.type,
        pattern.rank,
        pattern.length,
        pattern.wild_used,
        pattern.suit,
        _card_counter_key(tuple(pattern.cards)),
    )


def _is_in_hand(pattern: Pattern, hand: list[Card]) -> bool:
    hand_counts = Counter(hand)
    return all(
        hand_counts[card] >= needed
        for card, needed in Counter(pattern.cards).items()
    )


def is_bomb_pattern(pattern: Pattern) -> bool:
    """是否是炸弹类牌型。"""
    return is_bomb_type(pattern.type)


def enumerate_legal_patterns(
    state: GameState,
    player: int,
    *,
    include_bombs: bool = True,
) -> List[Pattern]:
    """枚举 player 当前可出的所有合法牌型。

    table 为空时返回所有可领出的牌型；table 非空时只返回能压过桌顶的牌型。
    """
    hand = state.hands[player]
    if not hand:
        return []

    table_top: Optional[Pattern] = state.table[-1] if state.table else None
    candidates: List[Pattern] = []
    seen: set[tuple] = set()

    for pattern in detect_patterns(hand, state.wild_card):
        if not include_bombs and is_bomb_pattern(pattern):
            continue
        if not _is_in_hand(pattern, hand):
            continue
        if table_top is not None and not pattern.can_be_played_on(
            table_top, level=state.level
        ):
            continue
        key = _pattern_key(pattern)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(pattern)

    return candidates


def _bomb_order_key(pattern: Pattern, level: int) -> tuple[int, int, int, int]:
    category, length, rank = bomb_strength(pattern, level=level)
    return (category, length, rank, pattern.wild_used)


def greedy_pattern_key(pattern: Pattern, level: int) -> tuple:
    """贪心排序：同型小牌优先，炸弹最后。"""
    if is_bomb_pattern(pattern):
        return (1, *_bomb_order_key(pattern, level), len(pattern.cards))
    return (
        0,
        pattern.weight,
        pattern.length,
        comparison_rank(pattern, level),
        pattern.wild_used,
        len(pattern.cards),
        _card_counter_key(tuple(pattern.cards)),
    )


def smallest_legal_pattern(state: GameState, player: int) -> Optional[Pattern]:
    """返回当前最小合法出牌；找不到则 None。"""
    candidates = enumerate_legal_patterns(state, player)
    if not candidates:
        return None

    table_top = state.table[-1] if state.table else None
    if table_top is None:
        return min(candidates, key=lambda p: greedy_pattern_key(p, state.level))

    same_type = [
        p
        for p in candidates
        if p.type == table_top.type and p.length == table_top.length
    ]
    if same_type:
        return min(same_type, key=lambda p: greedy_pattern_key(p, state.level))

    bombs = [p for p in candidates if is_bomb_pattern(p)]
    if bombs:
        return min(bombs, key=lambda p: greedy_pattern_key(p, state.level))
    return None

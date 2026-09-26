"""AI 候选出牌生成。

AI 不再手写各牌型枚举，而是复用规则层的 `detect_patterns()`：
先从当前手牌识别所有可出的牌型，再按桌顶牌过滤合法回应。
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from typing import List, Optional, TypeAlias

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


PatternKey: TypeAlias = tuple[
    object,
    int,
    int,
    int,
    int | None,
    tuple[tuple[int, int, int], ...],
]

# A "play" key describes what observers see, not which physical cards were used.
ObservableKey: TypeAlias = tuple[object, int, int, int, int | None, int]


def pattern_key(pattern: Pattern) -> PatternKey:
    """Return a stable public action key for information-set search.

    Equal physical cards from the two decks deliberately collapse into the
    same multiset representation.  The key therefore identifies the action a
    player can observe, without leaking which hidden-deck copy was sampled.
    """
    return (
        pattern.type,
        pattern.rank,
        pattern.length,
        pattern.wild_used,
        pattern.suit,
        _card_counter_key(tuple(pattern.cards)),
    )


def observable_key(pattern: Pattern) -> ObservableKey:
    """Key a *tree node* by the play an observer can see.

    `pattern_key` includes the exact card multiset, which is right for the root
    action list (the root must act on real cards) but wrong for the shared tree:
    every simulation samples fresh hidden hands, so the same play arrives as a
    different multiset and never matches an existing child. Measured effect of
    the exact-card key: 64 simulations produced exactly 64 non-root nodes, so
    no statistic was ever shared and `max_depth` / widening / priors were inert.

    Dropping the card multiset lets two worlds that play "the same pair" share
    one node, which is what makes the search a tree rather than a single layer.
    """
    return (
        pattern.type,
        pattern.rank,
        pattern.length,
        pattern.wild_used,
        pattern.suit,
        len(pattern.cards),
    )


@lru_cache(maxsize=4096)
def _patterns_in_hand(hand: tuple[Card, ...], wild: Card | None) -> tuple[Pattern, ...]:
    """Reuse material enumeration across paired worlds and unchanged hands."""
    counts = Counter(hand)
    seen: set[PatternKey] = set()
    patterns = []
    for pattern in detect_patterns(hand, wild):
        if any(counts[card] < needed for card, needed in Counter(pattern.cards).items()):
            continue
        key = pattern_key(pattern)
        if key not in seen:
            seen.add(key)
            patterns.append(pattern)
    return tuple(patterns)


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
    for pattern in _patterns_in_hand(tuple(hand), state.wild_card):
        if not include_bombs and is_bomb_pattern(pattern):
            continue
        if table_top is not None and not pattern.can_be_played_on(
            table_top, level=state.level
        ):
            continue
        candidates.append(pattern)

    return candidates


def material_variants(
    state: GameState,
    player: int,
    pattern: Pattern,
    *,
    limit: int = 2,
) -> list[Pattern]:
    """Find equivalent plays that spend different physical cards.

    The rule detector uses one representative for most natural combinations.
    Swapping one same-rank card can preserve a future straight flush or pair,
    so root search should be able to compare those material choices.
    """
    hand = state.hands[player]
    wild = state.wild_card
    available = Counter(hand)
    seen = {pattern_key(pattern)}
    variants: list[Pattern] = []
    for index, original in enumerate(pattern.cards):
        if original == wild or original.is_joker:
            continue
        for replacement in hand:
            if replacement.rank != original.rank or replacement == original:
                continue
            material = list(pattern.cards)
            material[index] = replacement
            counts = Counter(material)
            if any(counts[card] > available[card] for card in counts):
                continue
            for candidate in detect_patterns(material, wild):
                if (
                    candidate.type != pattern.type
                    or candidate.rank != pattern.rank
                    or candidate.length != pattern.length
                    or candidate.suit != pattern.suit
                    or Counter(candidate.cards) != counts
                ):
                    continue
                key = pattern_key(candidate)
                if key not in seen:
                    seen.add(key)
                    variants.append(candidate)
                    if len(variants) >= limit:
                        return variants
                break
    return variants


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

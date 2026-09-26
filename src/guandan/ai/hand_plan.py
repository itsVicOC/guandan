"""Bounded, cached estimates of how many plays a hand needs to go out.

The planner uses the rule engine's patterns as a set-cover search.  It never
looks at another player's hand, and its beam/node limits keep opening hands
cheap enough to score several candidate plays.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from math import ceil

from ..engine.card import Card
from ..engine.hand import Pattern, PatternType, effective_rank
from ..engine.rules.patterns import detect_patterns


def remaining_cards(cards: list[Card] | tuple[Card, ...], played: tuple[Card, ...]) -> tuple[Card, ...]:
    counts = Counter(cards)
    counts.subtract(played)
    return tuple(sorted(counts.elements()))


def _play_cost(pattern: Pattern, level: int) -> float:
    # A low singleton often requires another control play before it can leave.
    if pattern.type == PatternType.SINGLE:
        rank = effective_rank(pattern.rank, level)
        return 1.28 if rank < 11 else 0.92
    if pattern.type == PatternType.PAIR:
        return 1.08
    if pattern.type in (PatternType.BOMB, PatternType.STRAIGHT_FLUSH, PatternType.FOUR_JOKERS):
        return 0.82
    return 1.0


@lru_cache(maxsize=8192)
def _estimate(cards: tuple[Card, ...], wild: Card | None, level: int, width: int) -> float:
    if not cards:
        return 0.0
    patterns = detect_patterns(cards, wild)
    # Equivalent material can have different interpretations; use the cheapest
    # one for a future hand partition.  Keep all singles as a complete fallback.
    by_material: dict[tuple[Card, ...], Pattern] = {}
    for pattern in patterns:
        material = tuple(sorted(pattern.cards))
        previous = by_material.get(material)
        if previous is None or _play_cost(pattern, level) < _play_cost(previous, level):
            by_material[material] = pattern
    singles = [p for p in by_material.values() if len(p.cards) == 1]
    grouped = sorted(
        (p for p in by_material.values() if len(p.cards) > 1),
        key=lambda p: (-len(p.cards), p.wild_used, _play_cost(p, level)),
    )[:192]
    pool = grouped + singles
    by_card: dict[Card, list[Pattern]] = {}
    for pattern in pool:
        for card in set(pattern.cards):
            by_card.setdefault(card, []).append(pattern)

    beam: list[tuple[float, tuple[Card, ...]]] = [(0.0, cards)]
    best = float(len(cards)) * 1.28
    expanded = 0
    node_limit = max(64, width * 12)
    while beam and expanded < node_limit:
        next_beam: dict[tuple[Card, ...], float] = {}
        for spent, rest in beam:
            if not rest:
                best = min(best, spent)
                continue
            pivot = rest[0]
            have = Counter(rest)
            options = [
                pattern for pattern in by_card.get(pivot, ())
                if not (Counter(pattern.cards) - have)
            ]
            options.sort(key=lambda p: (_play_cost(p, level) / len(p.cards), -len(p.cards)))
            for pattern in options[:16]:
                after = remaining_cards(rest, pattern.cards)
                value = spent + _play_cost(pattern, level)
                if not after:
                    best = min(best, value)
                elif value + ceil(len(after) / 10) * 0.82 < best:
                    next_beam[after] = min(value, next_beam.get(after, float("inf")))
                expanded += 1
                if expanded >= node_limit:
                    break
            if expanded >= node_limit:
                break
        beam = sorted(
            ((value, rest) for rest, value in next_beam.items()),
            key=lambda item: item[0] + ceil(len(item[1]) / 8) * 0.9,
        )[:width]
    # Incomplete beam states can always be finished as singles.  This upper
    # bound prevents the node limit from making large hands look artificially good.
    for spent, rest in beam:
        best = min(best, spent + len(rest) * 1.28)
    return best


def estimate_remaining_plays(
    cards: list[Card] | tuple[Card, ...],
    wild: Card | None,
    level: int,
    *,
    width: int = 16,
) -> float:
    """Return a bounded weighted hand-partition estimate; lower is better."""
    return _estimate(tuple(sorted(cards)), wild, level, width)

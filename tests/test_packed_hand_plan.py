"""Packed prototype must preserve bounded planner outputs exactly."""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from guandan.ai.hand_plan import estimate_remaining_plays
from guandan.engine.card import Card, Suit
from scripts.ai_hand_plan_bitmask import load_counter_reference, packed_estimate

_estimate = load_counter_reference()


@settings(max_examples=160, deadline=None)
@given(st.lists(st.tuples(st.integers(2, 14), st.sampled_from([2, 3, 4, 5])), max_size=27),
       st.sampled_from([2, 9, 14]), st.sampled_from([1, 6, 16, 24]), st.booleans())
def test_packed_multisets_preserve_node_limited_estimates(material, level, width, has_wild):
    cards = tuple(sorted(Card(rank, Suit(suit)) for rank, suit in material))
    wild = Card(level, Suit.HEARTS) if has_wild else None
    assert packed_estimate(cards, wild, level, width) == _estimate(cards, wild, level, width)
    assert estimate_remaining_plays(cards, wild, level, width=width) == _estimate(cards, wild, level, width)


def test_large_duplicate_counts_and_wilds_do_not_overflow_packed_lanes():
    cards = tuple(sorted([Card(7, Suit.SPADES)] * 8 + [Card(9, Suit.HEARTS)] * 3
                         + [Card(100, Suit.SMALL_JOKER)] * 2 + [Card(101, Suit.BIG_JOKER)] * 2))
    for width in (1, 6, 16, 24):
        assert packed_estimate(cards, Card(9, Suit.HEARTS), 9, width) == _estimate(cards, Card(9, Suit.HEARTS), 9, width)


def test_production_cache_clear_recomputes_and_has_only_one_layer(monkeypatch):
    from guandan.ai import hand_plan

    assert not hasattr(hand_plan._estimate.__wrapped__, "cache_info")
    original = hand_plan.detect_patterns
    calls = []

    def counted(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(hand_plan, "detect_patterns", counted)
    cards = [Card(3, Suit.CLUBS), Card(3, Suit.HEARTS), Card(4, Suit.SPADES)]
    hand_plan._estimate.cache_clear()
    first = hand_plan.estimate_remaining_plays(cards, None, 2)
    assert hand_plan.estimate_remaining_plays(cards, None, 2) == first
    assert calls == [1]
    hand_plan._estimate.cache_clear()
    assert hand_plan.estimate_remaining_plays(cards, None, 2) == first
    assert calls == [1, 1]

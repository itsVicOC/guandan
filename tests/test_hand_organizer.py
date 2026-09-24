"""Display-only intelligent hand arrangement regressions."""
from __future__ import annotations

from collections import Counter

from guandan.engine.card import Card, Suit
from guandan.engine.hand import PatternType, sort_cards
from guandan.engine.rules.patterns import detect_patterns
from guandan.engine.state import make_initial_state
from guandan.ui.hand_organizer import (
    HandOrganizer,
    build_hand_arrangements,
    remap_selected_indices,
)


def _example_hand() -> list[Card]:
    return sort_cards([
        Card(3, Suit.HEARTS), Card(3, Suit.DIAMONDS),
        Card(4, Suit.HEARTS), Card(5, Suit.HEARTS),
        Card(6, Suit.HEARTS), Card(7, Suit.HEARTS),
        Card(8, Suit.CLUBS),
    ])


def test_arrangements_are_distinct_full_hand_partitions_with_legal_groups() -> None:
    wild = Card(2, Suit.HEARTS)
    duplicate = Card(8, Suit.SPADES)
    hand = sort_cards([
        wild, wild, duplicate, duplicate,
        Card(3, Suit.HEARTS), Card(3, Suit.DIAMONDS),
        Card(4, Suit.HEARTS), Card(5, Suit.HEARTS),
        Card(6, Suit.HEARTS), Card(7, Suit.HEARTS),
    ])

    layouts = build_hand_arrangements(hand, wild, 2)

    assert layouts
    assert layouts[0].name == "牌型·综合"
    assert len(layouts) <= len(PatternType) + 3
    assert {layout.kind for layout in layouts} >= {"pattern", "rank", "suit", "count"}
    for layout in layouts:
        assert Counter(layout.cards) == Counter(hand)
        assert all(0 < start < len(hand) for start in layout.group_starts)
        for group in layout.groups:
            if group.pattern is None:
                continue
            assert Counter(group.cards) == Counter(group.pattern.cards)
            assert any(
                candidate.type == group.pattern.type
                and Counter(candidate.cards) == Counter(group.cards)
                for candidate in detect_patterns(group.cards, wild)
            )


def test_arrangement_cycle_and_focus_survive_hand_changes() -> None:
    base = _example_hand()
    organizer = HandOrganizer()
    organizer.sync(base, None, 2)
    assert organizer.status == ""

    assert organizer.advance()
    assert organizer.status.startswith("牌型·综合 ")
    pair_index = next(
        index for index, layout in enumerate(organizer.arrangements)
        if layout.focus == PatternType.PAIR
    )
    assert organizer.select(pair_index)
    assert organizer.status.startswith("对子优先 ")
    pair_layout = organizer.cards

    organizer.sync(sort_cards([*base, Card(9, Suit.CLUBS)]), None, 2)
    assert organizer.status.startswith("对子优先 ")
    assert Counter(organizer.cards) == Counter([*base, Card(9, Suit.CLUBS)])

    no_pair = sort_cards([card for card in base if card != Card(3, Suit.DIAMONDS)])
    organizer.sync(no_pair, None, 2)
    assert organizer.status.startswith("牌型·综合 ")
    assert organizer.cards != pair_layout

    layouts = build_hand_arrangements(no_pair, None, 2)
    for _ in range(len(layouts)):
        assert organizer.advance()
    assert organizer.status.startswith("牌型·综合 ")


def test_arrangements_ignore_hand_with_only_singles() -> None:
    organizer = HandOrganizer()
    card = Card(9, Suit.CLUBS)
    organizer.sync([card], None, 2)

    assert not organizer.available
    assert not organizer.advance()
    assert organizer.cards == (card,)


def test_active_cycle_returns_to_first_layout_after_temporary_single_only_hand() -> None:
    organizer = HandOrganizer()
    base = _example_hand()
    organizer.sync(base, None, 2)
    assert organizer.advance()
    organizer.sync([Card(9, Suit.CLUBS)], None, 2)
    assert not organizer.available
    organizer.sync(base, None, 2)
    assert organizer.status.startswith("牌型·综合 ")


def test_normal_deals_have_bounded_valid_arrangements() -> None:
    for seed in range(20):
        state = make_initial_state(level=2, first_player=0, seed=seed)
        hand = sort_cards(state.hands[0])
        layouts = build_hand_arrangements(hand, state.wild_card, state.level)
        assert len(layouts) <= len(PatternType) + 3
        assert all(Counter(layout.cards) == Counter(hand) for layout in layouts)


def test_comprehensive_search_reduces_fragmentation_on_fixed_deal() -> None:
    state = make_initial_state(level=2, first_player=0, seed=0)
    layout = build_hand_arrangements(sort_cards(state.hands[0]), state.wild_card, 2)[0]
    plays = sum(group.pattern is not None for group in layout.groups)
    plays += sum(len(group.cards) for group in layout.groups if group.pattern is None)

    assert plays <= 10


def test_comprehensive_layout_keeps_power_groups_in_front() -> None:
    hand = sort_cards([
        Card(3, Suit.HEARTS), Card(3, Suit.DIAMONDS),
        Card(3, Suit.SPADES), Card(3, Suit.CLUBS),
        Card(4, Suit.HEARTS), Card(5, Suit.HEARTS),
        Card(6, Suit.HEARTS), Card(7, Suit.HEARTS),
        Card(8, Suit.HEARTS),
    ])
    layouts = build_hand_arrangements(hand, None, 2)

    assert [group.pattern.type for group in layouts[0].groups] == [
        PatternType.BOMB, PatternType.STRAIGHT_FLUSH,
    ]
    # The bomb-first focus is identical to comprehensive and is skipped.
    assert layouts[1].focus == PatternType.STRAIGHT_FLUSH
    assert next(index for index, item in enumerate(layouts) if item.kind == "rank") > 1
    assert Counter(layouts[0].cards) == Counter(hand)


def test_bomb_is_kept_ahead_of_an_overlapping_plain_straight() -> None:
    hand = sort_cards([
        Card(3, Suit.HEARTS), Card(3, Suit.DIAMONDS),
        Card(3, Suit.SPADES), Card(3, Suit.CLUBS),
        Card(4, Suit.DIAMONDS), Card(5, Suit.HEARTS),
        Card(6, Suit.DIAMONDS), Card(7, Suit.HEARTS),
    ])

    layout = build_hand_arrangements(hand, None, 2)[0]

    assert layout.groups[0].pattern is not None
    assert layout.groups[0].pattern.type == PatternType.BOMB
    assert Counter(layout.cards) == Counter(hand)


def test_pair_focus_can_use_multiple_copies_of_the_same_combination() -> None:
    hand = sort_cards([
        Card(3, Suit.HEARTS), Card(3, Suit.HEARTS),
        Card(3, Suit.DIAMONDS), Card(3, Suit.DIAMONDS),
    ])
    layouts = build_hand_arrangements(hand, None, 2)
    pair_layout = next(layout for layout in layouts if layout.focus == PatternType.PAIR)

    assert len(pair_layout.groups) == 2
    assert all(group.pattern is not None and group.pattern.type == PatternType.PAIR
               for group in pair_layout.groups)
    assert Counter(pair_layout.cards) == Counter(hand)


def test_basic_modes_work_even_without_a_multi_card_pattern() -> None:
    hand = sort_cards([
        Card(9, Suit.HEARTS), Card(7, Suit.CLUBS), Card(3, Suit.SPADES),
    ])
    organizer = HandOrganizer()
    organizer.sync(hand, None, 2)

    assert [layout.kind for layout in organizer.arrangements] == ["rank", "suit", "count"]
    assert organizer.available
    assert organizer.select(1)
    assert organizer.status.startswith("花色理 ")
    assert organizer.playable_group_at(0) is None
    organizer.reset()
    assert organizer.cards == tuple(hand)


def test_manual_locks_reserve_real_cards_across_every_layout_and_unlock() -> None:
    hand = sort_cards([
        Card(3, Suit.HEARTS), Card(3, Suit.DIAMONDS),
        Card(3, Suit.SPADES), Card(3, Suit.CLUBS),
        Card(4, Suit.HEARTS), Card(5, Suit.HEARTS),
        Card(6, Suit.HEARTS), Card(7, Suit.HEARTS),
        Card(8, Suit.HEARTS),
    ])
    organizer = HandOrganizer()
    organizer.sync(hand, None, 2, hand_id="round-one")
    organizer.select(next(index for index, layout in enumerate(organizer.arrangements)
                          if layout.kind == "suit"))
    bomb = {index for index, card in enumerate(organizer.cards) if card.rank == 3}

    assert organizer.lock_action(bomb) == "lock"
    assert organizer.toggle_lock(bomb) == "locked"
    assert organizer.locked_count == 1
    assert organizer.current is not None and organizer.current.kind == "suit"
    assert organizer.display_groups[0].locked
    assert organizer.display_groups[0].pattern.type == PatternType.BOMB
    assert organizer.lock_action({0}) is None
    for _ in organizer.arrangements:
        assert organizer.advance()
        assert organizer.display_groups[0].locked
        assert Counter(organizer.cards) == Counter(hand)
        assert not any(group.locked for group in organizer.display_groups[1:])

    flush = {
        index for index, card in enumerate(organizer.cards)
        if card.suit == Suit.HEARTS and card.rank in {4, 5, 6, 7, 8}
    }
    assert organizer.toggle_lock(flush) == "locked"
    assert organizer.locked_count == 2
    assert Counter(organizer.cards) == Counter(hand)
    assert not organizer.available
    assert organizer.lock_action(set(range(4))) == "unlock"
    assert organizer.toggle_lock(set(range(4))) == "unlocked"
    assert organizer.locked_count == 1
    assert organizer.display_groups[0].pattern.type == PatternType.STRAIGHT_FLUSH

    changed = [card for card in hand if card != Card(8, Suit.HEARTS)]
    organizer.sync(changed, None, 2, hand_id="round-one")
    assert organizer.locked_count == 0
    organizer.sync(hand, None, 2, hand_id="round-two")
    assert organizer.locked_count == 0


def test_manual_locks_handle_identical_cards_and_hand_changes() -> None:
    three_heart = Card(3, Suit.HEARTS)
    three_diamond = Card(3, Suit.DIAMONDS)
    hand = sort_cards([three_heart, three_heart, three_diamond, three_diamond])
    organizer = HandOrganizer()
    organizer.sync(hand, None, 2, hand_id="one")
    first = {
        next(index for index, card in enumerate(organizer.cards) if card == three_heart),
        next(index for index, card in enumerate(organizer.cards) if card == three_diamond),
    }
    assert organizer.toggle_lock(first) == "locked"
    second = set(range(2, 4))
    assert organizer.toggle_lock(second) == "locked"
    assert Counter(organizer.cards) == Counter(hand)
    assert organizer.locked_count == 2

    organizer.sync(sort_cards([three_heart, three_diamond, three_diamond]), None, 2, hand_id="one")
    assert organizer.locked_count == 1
    assert Counter(organizer.cards) == Counter([three_heart, three_diamond, three_diamond])
    organizer.sync(hand, None, 2, hand_id="two")
    assert organizer.locked_count == 0


def test_selected_duplicate_occurrence_survives_reorder() -> None:
    duplicate = Card(3, Suit.HEARTS)
    other = Card(4, Suit.CLUBS)

    assert remap_selected_indices((duplicate, other, duplicate), {2},
                                  (duplicate, duplicate, other)) == {1}

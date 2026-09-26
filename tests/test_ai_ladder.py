"""Tactical and information-boundary regressions for the revised ladder."""
from __future__ import annotations

import copy
import random

import pytest

from guandan.ai.candidates import enumerate_legal_patterns, material_variants, pattern_key
from guandan.ai.hand_plan import estimate_remaining_plays
from guandan.ai.mcts.endgame_solver import UNSOLVED, solve_endgame
from guandan.ai.mcts.information_set import _apply_action
from guandan.ai.mcts.root_search import _ranking_score, _RootArm
from guandan.ai.mcts.search import (
    _evaluate_result,
    planned_position_features,
    planned_position_value,
)
from guandan.ai.memory import PlayedTracker
from guandan.ai.play import play_or_pass
from guandan.ai.strategies.advanced import AdvancedStrategy
from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
from guandan.ai.strategies.intermediate import IntermediateStrategy
from guandan.ai.strategies.novice import NoviceStrategy
from guandan.ai.strategies.professional import ProfessionalStrategy
from guandan.ai.tactics import _control_bonus
from guandan.ai.tribute import choose_ai_tribute_cards
from guandan.engine.card import RANK_BIG_JOKER, RANK_SMALL_JOKER, Card, Suit
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.rules.tributes import apply_tribute_flow, legal_return_cards
from guandan.engine.state import GameState, clone_state_for_search, make_initial_state


def card(rank: int, suit: Suit = Suit.CLUBS) -> Card:
    return Card(rank, suit)


def test_hand_plan_values_a_natural_straight() -> None:
    straight = [card(rank) for rank in range(3, 8)]
    broken = [card(rank) for rank in (3, 5, 7, 9, 11)]
    assert estimate_remaining_plays(straight, None, 2) < estimate_remaining_plays(
        broken, None, 2
    )


def test_planned_value_distinguishes_groups_and_is_team_symmetric() -> None:
    steel = [card(3), card(3), card(3, Suit.SPADES), card(4), card(4), card(4, Suit.SPADES)]
    scattered = [card(rank, Suit.HEARTS) for rank in (3, 5, 7, 9, 11, 13)]
    state = GameState(
        level=2, wild_card=None,
        hands=[steel, scattered, [card(6), card(8), card(10)], [card(6), card(8), card(10)]],
        turn_index=0, leader=0,
    )
    structured_value = planned_position_value(state, 0)
    assert planned_position_features(state, 0) == pytest.approx(
        tuple(-feature for feature in planned_position_features(state, 1))
    )
    assert structured_value + planned_position_value(state, 1) == pytest.approx(1.0)
    state.hands[0] = scattered
    assert structured_value > planned_position_value(state, 0) + 0.1


def test_material_cache_does_not_cache_level_or_trick_legality() -> None:
    state = GameState(
        level=2, wild_card=None, hands=[[card(2), card(14)], [], [], []],
        turn_index=0,
        table=[Pattern(PatternType.SINGLE, 13, 1, (card(13),))],
    )
    patterns = enumerate_legal_patterns(state, 0)
    assert {pattern.rank for pattern in patterns} == {2, 14}
    patterns.clear()
    state.level = 9
    assert {pattern.rank for pattern in enumerate_legal_patterns(state, 0)} == {14}


def test_unseen_joker_pair_prevents_false_level_pair_control() -> None:
    pair = Pattern(PatternType.PAIR, 2, 1, (card(2), card(2, Suit.SPADES)))
    state = GameState(
        level=2, wild_card=None, hands=[list(pair.cards), [], [], []], turn_index=0
    )
    tracker = PlayedTracker()
    assert _control_bonus(state, 0, pair, tracker) == 0.0
    tracker.played_by_rank = {RANK_SMALL_JOKER: 2, RANK_BIG_JOKER: 2}
    assert _control_bonus(state, 0, pair, tracker) > 0.0


def test_unfinished_value_respects_already_decided_head_place() -> None:
    state = make_initial_state(seed=99)
    state.finish_order = [1, 0]
    state.hands[0] = []
    state.hands[1] = []
    state.hands[2] = [Card(RANK_BIG_JOKER, Suit.BIG_JOKER)]
    state.turn_index = 2
    losing_team_value = _evaluate_result(state, 0)
    winning_team_value = _evaluate_result(state, 1)
    assert 0.0 <= losing_team_value <= 7.0 / 30.0
    assert winning_team_value >= 23.0 / 30.0
    assert losing_team_value + winning_team_value == pytest.approx(1.0)
    state.finish_order = [0, 2]
    state.hands[2] = []
    assert _evaluate_result(state, 0) == 1.0
    assert _evaluate_result(state, 1) == 0.0


def test_finish_prior_cannot_overrule_clearly_better_rollouts() -> None:
    tempting_finish = _RootArm(("finish",), None, 12.0, [0.2] * 4)
    better = _RootArm(("better",), None, 1.0, [0.7] * 4)
    assert _ranking_score(better, 0.18) > _ranking_score(tempting_finish, 0.18)


def test_endgame_cache_keeps_distinct_trick_owners() -> None:
    from guandan.ai.mcts.endgame_solver import _key
    from guandan.engine.events import TurnPlayed

    top = Pattern(PatternType.SINGLE, 3, 1, (card(3),))
    state = GameState(
        level=2, wild_card=None,
        hands=[[card(4)], [card(5)], [card(6)], [card(7)]],
        turn_index=0, leader=1, table=[top],
        history=[TurnPlayed(player=1, pattern=top, hand_remaining=1)],
    )
    other = copy.deepcopy(state)
    other.history = [TurnPlayed(player=2, pattern=top, hand_remaining=1)]
    assert _key(state, 12) != _key(other, 12)


def test_endgame_cache_does_not_reuse_fail_low_as_exact() -> None:
    from guandan.ai.mcts.endgame_solver import _Budget, _key, _minimax

    state = GameState(
        level=2, wild_card=None,
        hands=[[card(3)], [card(4)], [card(5)], [card(6)]],
        turn_index=0, leader=0,
    )
    budget = _Budget(deadline=float("inf"), nodes_left=30000)
    bound = _minimax(state, 0, 12, budget, 0.99, 1.0)
    assert bound < 0.99
    assert _key(state, 12) not in budget.cache
    fresh = _Budget(deadline=float("inf"), nodes_left=30000)
    assert _minimax(state, 0, 12, budget, 0.0, 1.0) == _minimax(
        state, 0, 12, fresh, 0.0, 1.0
    )


def test_deadline_discards_incomplete_rollout(monkeypatch: pytest.MonkeyPatch) -> None:
    import guandan.ai.mcts.root_search as search

    state = make_initial_state(seed=17)
    player = state.current_player()
    actions = search.root_action_candidates(state, player, max_actions=6)[:2]
    assert len(actions) == 2
    clock = [0.0]
    calls = [0]

    def rollout(*args, **kwargs):
        calls[0] += 1
        clock[0] = 0.01 if calls[0] == 1 else 1.0
        return 0.2 if calls[0] == 1 else 1.0

    monkeypatch.setattr(search, "root_action_candidates", lambda *a, **k: actions)
    monkeypatch.setattr(search, "simulate_state", rollout)
    monkeypatch.setattr(search.time, "perf_counter", lambda: clock[0])
    result = search.root_action_search(
        state, player, rng=random.Random(2), iterations=20, time_budget_ms=100
    )
    assert result.budget_limited
    assert result.simulations == 1
    assert result.pattern == actions[0]


def test_partial_sampling_round_does_not_bias_paired_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import guandan.ai.mcts.root_search as search

    state = make_initial_state(seed=18)
    player = state.current_player()
    actions = search.root_action_candidates(state, player, max_actions=6)[:2]
    values = iter((0.4, 0.6, 0.0))
    monkeypatch.setattr(search, "root_action_candidates", lambda *a, **k: actions)
    monkeypatch.setattr(search, "simulate_state", lambda *a, **k: next(values))
    result = search.root_action_search(
        state, player, rng=random.Random(3), iterations=3, prior_weight=0.0
    )
    assert result.simulations == 3
    assert result.pattern == actions[1]
    assert result.actions[1].mean_value == 0.6


def test_paired_uncertainty_uses_only_common_worlds(monkeypatch) -> None:
    import guandan.ai.mcts.root_search as search

    state = make_initial_state(seed=18)
    actions = search.root_action_candidates(state, 0, max_actions=6)[:2]
    # Second round rotates B then A; the fifth evaluation is an incomplete
    # third world and must not enter either the mean or its paired error.
    values = iter((0.2, 0.3, 0.7, 0.4, 1.0))
    monkeypatch.setattr(search, "root_action_candidates", lambda *a, **k: actions)
    monkeypatch.setattr(search, "simulate_state", lambda *a, **k: next(values))
    result = search.root_action_search(
        state, 0, rng=random.Random(3), iterations=5, prior_weight=0.0,
        reference_actions=(actions[0],),
    )
    reference, alternative = result.actions
    assert alternative.reference_key == reference.action_key
    assert alternative.mean_value - reference.mean_value == pytest.approx(0.2)
    assert alternative.paired_standard_error == pytest.approx(0.1)
    assert reference.paired_standard_error == 0.0


def test_confidence_guard_demands_more_gain_when_worlds_disagree() -> None:
    from dataclasses import replace

    from guandan.ai.mcts.information_set import ActionStatistics

    reference = ActionStatistics(("reference",), None, 20, 20, 0.4, 1.0)
    alternative = ActionStatistics(
        ("alternative",), None, 20, 20, 0.6, 1.0,
        reference_key=reference.action_key, paired_standard_error=0.02,
    )
    guarded = DaiChangshengStrategy()
    assert guarded.confidence_guard
    ordinary = DaiChangshengStrategy(mcts_overrides={"confidence_guard": 0})
    assert guarded._minimum_search_gain(alternative, reference) < 0.1
    assert guarded._minimum_search_gain(
        replace(alternative, paired_standard_error=0.2), reference
    ) > 0.3
    assert ordinary._minimum_search_gain(alternative, reference) == 0.14
    assert guarded._minimum_search_gain(
        replace(alternative, reference_key=("different",)), reference
    ) == 0.14


def test_novice_pass_is_decision_not_rng() -> None:
    state = GameState(
        level=2,
        wild_card=None,
        hands=[[card(7)], [card(8)], [card(9)], [card(10)]],
        turn_index=0,
        leader=1,
        table=[Pattern(PatternType.SINGLE, 6, 1, (card(6),))],
    )
    first = copy.deepcopy(state)
    second = copy.deepcopy(state)
    play_or_pass(first, 0, NoviceStrategy(), random.Random(1))
    play_or_pass(second, 0, NoviceStrategy(), random.Random(999))
    assert first.table == second.table
    assert first.hands == second.hands


def test_forced_pass_skips_both_sampling_and_endgame_search(monkeypatch) -> None:
    def unexpected(*args, **kwargs):
        raise AssertionError("a forced pass must not spend search budget")

    monkeypatch.setattr("guandan.ai.strategies.professional.root_action_search", unexpected)
    monkeypatch.setattr("guandan.ai.strategies.dachangsheng.solve_endgame", unexpected)
    joker = Card(RANK_BIG_JOKER, Suit.BIG_JOKER)
    state = GameState(
        level=2, wild_card=None,
        hands=[[card(3), card(5)], [card(4)], [card(6)], [card(7)]],
        turn_index=0, leader=1,
        table=[Pattern(PatternType.SINGLE, RANK_BIG_JOKER, 1, (joker,))],
    )
    for strategy in (ProfessionalStrategy(), DaiChangshengStrategy()):
        rng_state = strategy.rng.getstate()
        assert strategy.select_pattern(state, 0) is None
        assert strategy.last_search is None
        assert strategy.rng.getstate() == rng_state


def test_reported_single_is_blocked_when_possible() -> None:
    state = GameState(
        level=2,
        wild_card=None,
        hands=[[card(12), card(3)], [card(4)], [card(6)], [card(5)]],
        turn_index=0,
        leader=1,
        table=[Pattern(PatternType.SINGLE, 10, 1, (card(10),))],
    )
    for strategy in (NoviceStrategy(), IntermediateStrategy(), AdvancedStrategy()):
        selected = strategy.select_pattern(state, 0)
        assert selected is not None and selected.cards == (card(12),)


def test_nonurgent_single_does_not_waste_bomb() -> None:
    four_nines = [
        card(9, suit)
        for suit in (Suit.CLUBS, Suit.DIAMONDS, Suit.HEARTS, Suit.SPADES)
    ]
    state = GameState(
        level=2,
        wild_card=None,
        hands=[[card(3), *four_nines], [card(4)] * 8, [card(5)] * 8, [card(6)] * 8],
        turn_index=0,
        leader=1,
        table=[Pattern(PatternType.SINGLE, 12, 1, (card(12),))],
    )
    for strategy in (NoviceStrategy(), IntermediateStrategy(), AdvancedStrategy()):
        assert strategy.select_pattern(state, 0) is None


def test_catch_wind_lead_sheds_a_group() -> None:
    state = GameState(
        level=2,
        wild_card=None,
        hands=[[card(3), card(3, Suit.DIAMONDS), card(9)], [card(4)], [], [card(5)]],
        turn_index=0,
        leader=2,
        finish_order=[2],
    )
    for strategy in (NoviceStrategy(), IntermediateStrategy(), AdvancedStrategy()):
        selected = strategy.select_pattern(state, 0)
        assert selected is not None
        assert selected.type == PatternType.PAIR


def test_advanced_can_take_over_from_teammate_to_shed_a_weak_hand() -> None:
    straight = tuple(card(rank, Suit.SPADES) for rank in range(5, 10))
    state = GameState(
        level=2,
        wild_card=None,
        hands=[
            [*straight, card(3), card(11)],
            [card(rank, Suit.DIAMONDS) for rank in range(3, 11)],
            [card(rank, Suit.HEARTS) for rank in range(3, 15)],
            [card(rank, Suit.CLUBS) for rank in range(3, 11)],
        ],
        turn_index=0,
        leader=2,
        table=[
            Pattern(
                PatternType.STRAIGHT,
                8,
                5,
                tuple(card(rank, Suit.HEARTS) for rank in range(4, 9)),
            )
        ],
    )
    selected = AdvancedStrategy().select_pattern(state, 0)
    assert selected is not None
    assert selected.type == PatternType.STRAIGHT


def test_root_can_compare_same_rank_different_suits() -> None:
    cards = [card(3, Suit.HEARTS), card(3, Suit.DIAMONDS), card(3, Suit.SPADES)]
    state = GameState(level=2, wild_card=None, hands=[cards, [], [], []], turn_index=0)
    base = Pattern(PatternType.PAIR, 3, 1, tuple(cards[:2]))
    variants = material_variants(state, 0, base)
    assert variants
    assert all(pattern_key(p) != pattern_key(base) for p in variants)
    assert all(p.type == PatternType.PAIR for p in variants)


def test_tribute_policy_returns_legal_card_without_changing_rules() -> None:
    hands = [
        [card(3), card(3, Suit.DIAMONDS), card(4), card(9)],
        [card(5), card(6)],
        [card(7), card(8)],
        [card(14), card(10)],
    ]
    tribute, returned = choose_ai_tribute_cards(
        [0, 1, 2], hands, level=2, wild_card=None, difficulties=[2, 2, 2, 2]
    )
    assert 3 in tribute and 0 in returned
    assert returned[0] in legal_return_cards([*hands[0], tribute[3]], 2)
    copied = copy.deepcopy(hands)
    result = apply_tribute_flow(
        [0, 1, 2], copied, level=2, wild_card=None,
        tribute_choices=tribute, return_choices=returned,
    )
    assert result.exchanges[0].return_card == returned[0]


def test_sampled_endgame_ignores_actual_opponent_cards() -> None:
    from dataclasses import replace

    from guandan.engine.events import ShuffleDeal

    state = make_initial_state(seed=1)
    novice = NoviceStrategy()
    rng = random.Random(1)
    for _ in range(76):
        play_or_pass(state, state.current_player(), novice, rng)
    assert not state.finished
    assert list(map(len, state.hands)) == [0, 5, 1, 3]
    player = state.current_player()
    legal = enumerate_legal_patterns(state, player)
    assert len(legal) >= 2
    assert not any(len(pattern.cards) == state.hand_size(player) for pattern in legal)
    altered = copy.deepcopy(state)
    altered.history = [
        replace(event, seed=event.seed + 1) if isinstance(event, ShuffleDeal) else event
        for event in altered.history
    ]
    opponents = [seat for seat in range(4) if seat != player and altered.hands[seat]]
    assert len(opponents) >= 2
    first, second = opponents[:2]
    a, b = next(
        (a, b) for a in altered.hands[first] for b in altered.hands[second] if a != b
    )
    altered.hands[first].remove(a)
    altered.hands[second].remove(b)
    altered.hands[first].append(b)
    altered.hands[second].append(a)
    assert altered.hands != state.hands
    first_choice = solve_endgame(
        state, player, rng=random.Random(42), deadline=float("inf")
    )
    second_choice = solve_endgame(
        altered, player, rng=random.Random(42), deadline=float("inf")
    )
    assert first_choice is not UNSOLVED
    assert first_choice == second_choice
    fixed_work = DaiChangshengStrategy(
        rng=random.Random(42), mcts_overrides={"time_budget_ms": 0}
    )
    assert fixed_work.select_pattern(state, player) == first_choice
    assert fixed_work.last_search is None


def test_all_tiers_ignore_private_opponent_card_allocation() -> None:
    from dataclasses import replace

    from guandan.engine.events import ShuffleDeal

    state = make_initial_state(seed=117)
    rng = random.Random(117)
    novice = NoviceStrategy()
    while not state.finished and (
        state.hand_size(state.current_player()) > 15
        or not enumerate_legal_patterns(state, state.current_player())
    ):
        play_or_pass(state, state.current_player(), novice, rng)
    assert not state.finished
    player = state.current_player()
    altered = copy.deepcopy(state)
    # The replay seed can reconstruct the deal but is not player-visible
    # card knowledge. Search must ignore it as well as the actual hidden hands.
    altered.history = [
        replace(event, seed=event.seed + 1) if isinstance(event, ShuffleDeal) else event
        for event in altered.history
    ]
    opponents = [seat for seat in range(4) if seat != player and altered.hands[seat]]
    assert len(opponents) >= 2
    first, second = opponents[:2]
    a, b = next(
        (a, b) for a in altered.hands[first] for b in altered.hands[second] if a != b
    )
    altered.hands[first].remove(a)
    altered.hands[second].remove(b)
    altered.hands[first].append(b)
    altered.hands[second].append(a)
    assert altered.hands != state.hands
    strategies = [
        (NoviceStrategy(), NoviceStrategy()),
        (IntermediateStrategy(), IntermediateStrategy()),
        (AdvancedStrategy(), AdvancedStrategy()),
        (
            ProfessionalStrategy(iterations=24, time_budget_ms=0, rng=random.Random(8)),
            ProfessionalStrategy(iterations=24, time_budget_ms=0, rng=random.Random(8)),
        ),
        (
            DaiChangshengStrategy(
                rng=random.Random(8),
                mcts_overrides={"iterations": 24, "time_budget_ms": 0},
            ),
            DaiChangshengStrategy(
                rng=random.Random(8),
                mcts_overrides={"iterations": 24, "time_budget_ms": 0},
            ),
        ),
    ]
    for original_strategy, altered_strategy in strategies:
        original_action = original_strategy.select_pattern(state, player)
        altered_action = altered_strategy.select_pattern(altered, player)
        assert original_action == altered_action
        original_search = getattr(original_strategy, "last_search", None)
        altered_search = getattr(altered_strategy, "last_search", None)
        if isinstance(original_strategy, ProfessionalStrategy):
            assert original_search is not None
            assert altered_search is not None
            assert original_search.actions == altered_search.actions
            assert original_search.sampled_worlds == altered_search.sampled_worlds
        assert _apply_action(clone_state_for_search(state), player, original_action)

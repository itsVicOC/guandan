"""Match objective, local-information tactics and bounded search regressions."""
from __future__ import annotations

import copy
import random
import time
from dataclasses import replace

import pytest

from guandan.ai.belief import card_owner_likelihood, collect_pass_evidence
from guandan.ai.candidates import _exact_material_cache, enumerate_exact_small_hand_patterns
from guandan.ai.lead_chain import actor_response, evaluate_leads
from guandan.ai.match_value import (
    SCORES,
    continuation_value,
    load_model,
    outcome_probabilities,
    outcome_value,
    successor,
)
from guandan.ai.mcts.endgame_solver import _Budget, _minimax, search_endgame
from guandan.ai.mcts.search import _evaluate_result, rank_position_features
from guandan.ai.partner_model import style_probabilities
from guandan.ai.strategies.advanced import AdvancedStrategy
from guandan.engine.card import RANK_BIG_JOKER, Card, Suit
from guandan.engine.events import Pass, ShuffleDeal, TurnPlayed
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.state import GameState, _finish_game, make_initial_state


def card(rank):
    return Card(rank, Suit.CLUBS)


def settled(levels, counts, head, place):
    partner, enemy = (head + 2) % 4, 1 - head
    orders = {2: [head, partner, enemy], 3: [head, enemy, partner], 4: [head, enemy, (enemy + 2) % 4]}
    order = orders[place]
    last = next(s for s in range(4) if s not in order)
    hands = [[], [], [], []]
    hands[last] = [card(3)]
    state = GameState(level=levels[head], wild_card=None, team_levels=list(levels), a_failure_counts=list(counts),
                      hands=hands, finish_order=order, turn_index=last)
    _finish_game(state)
    return state


def test_all_match_score_transitions_match_the_engine():
    for l0, c0 in SCORES:
        for l1, c1 in SCORES:
            for head in (0, 1):
                for place in (2, 3, 4):
                    state = settled((l0, l1), (c0, c1), head, place)
                    levels, counts, winner = successor((l0, l1), (c0, c1), head, place)
                    assert levels == tuple(state.team_levels_final)
                    assert counts == tuple(state.a_failure_counts)
                    assert winner == state.winner_team


@pytest.mark.parametrize("head", [0, 1])
def test_failed_a_still_has_future_value_and_third_failure_is_costly(head):
    values = []
    for prior in (0, 1, 2):
        levels, counts = [9, 9], [0, 0]
        levels[head], counts[head] = 14, prior
        state = settled(levels, counts, head, 4)
        own, other = _evaluate_result(state, head), _evaluate_result(state, 1 - head)
        assert 0.0 < own < 1.0 and own + other == pytest.approx(1.0)
        values.append(own)
    assert values[0] > values[1] > values[2]


@pytest.mark.parametrize("head", [0, 1])
@pytest.mark.parametrize("place", [2, 3])
def test_only_actual_match_success_gets_terminal_one(head, place):
    state = settled((14, 14), (2, 2), head, place)
    assert state.match_finished
    assert _evaluate_result(state, head) == 1.0
    assert _evaluate_result(state, 1 - head) == 0.0
    ordinary = settled((2, 2), (0, 0), head, place)
    assert 0.0 < _evaluate_result(ordinary, head) < 1.0


def test_model_has_training_coverage_and_exchange_symmetry():
    model = load_model()
    assert model["meta"]["holdout_deals"] == 192
    assert all(n > 0 for n in model["meta"]["transition_training_games"].values())
    for key, value in model["continuation"].items():
        l0, c0, l1, c1, head, place = map(int, key.split(","))
        reversed_value = continuation_value((l1, l0), (c1, c0), 1 - head, place, 0)
        assert value + reversed_value == pytest.approx(1.0, abs=1e-9)


def test_rank_features_include_a_pressure_and_model_is_symmetric():
    state = make_initial_state(seed=119007, level=14, team_levels=[14, 9], a_failure_counts=[2, 0])
    own, other = rank_position_features(state, 0), rank_position_features(state, 1)
    assert own == pytest.approx(tuple(-v for v in other))
    assert own[-2] == 1.0
    original = outcome_probabilities(own)
    exchanged = outcome_probabilities(other)
    assert sum(original) == pytest.approx(1.0)
    assert original == pytest.approx(exchanged[3:] + exchanged[:3])
    earlier = copy.deepcopy(state)
    earlier.a_failure_counts[0] = 0
    assert rank_position_features(earlier, 0) != own


@pytest.mark.parametrize("level", [2, 9, 14])
@pytest.mark.parametrize("seat", range(4))
def test_controlled_single_takeover_can_finish_in_two_without_five_card_gap(level, seat):
    top = Pattern(PatternType.SINGLE, 13, 1, (card(13),))
    hands = [[Card(RANK_BIG_JOKER, Suit.BIG_JOKER), card(3), Card(3, Suit.SPADES)],
             [card(8), card(9)], [card(7)] * 6, [card(10), card(11)]]
    hands = [hands[(s - seat) % 4] for s in range(4)]
    state = GameState(level=level, wild_card=None, hands=hands, turn_index=seat, leader=(seat + 2) % 4,
                      table=[top], history=[TurnPlayed((seat + 2) % 4, top, 6)])
    action = AdvancedStrategy(team_tactics=True).select_pattern(state, seat)
    assert action is not None and action.type == PatternType.SINGLE and action.rank == RANK_BIG_JOKER


def test_lead_chain_and_style_model_ignore_private_hands_and_seed():
    state = make_initial_state(seed=119015)
    patterns = AdvancedStrategy().select_pattern(state, 0)
    assert patterns is not None
    changed = copy.deepcopy(state)
    for seat in (1, 2, 3):
        changed.hands[seat] = [card(12)] * state.hand_size(seat)
    changed.history = [replace(e, seed=12345) if isinstance(e, ShuffleDeal) else e for e in changed.history]
    assert evaluate_leads(state, 0, [patterns]) == evaluate_leads(changed, 0, [patterns])
    assert actor_response(state, 0) == actor_response(changed, 0)
    assert style_probabilities(state, 2) == style_probabilities(changed, 2)


def test_correlated_passes_are_not_repeated_certain_negative_evidence():
    first = Pattern(PatternType.SINGLE, 3, 1, (card(3),))
    second = Pattern(PatternType.SINGLE, 4, 1, (card(4),))
    third = Pattern(PatternType.SINGLE, 5, 1, (card(5),))
    state = GameState(level=2, wild_card=None, hands=[[], [], [], []], turn_index=0,
                      history=[TurnPlayed(0, first, 20), Pass(3, 20), TurnPlayed(2, second, 20),
                              Pass(1, 20), TurnPlayed(0, third, 19), Pass(3, 20)])
    evidence = collect_pass_evidence(state)
    assert sum(e.player == 3 for e in evidence) == 1
    assert 0.30 <= card_owner_likelihood(card(14), 3, evidence * 100, level=2) < 1.0


def test_exact_material_enumeration_is_interruptible_without_caching_partial_results():
    _exact_material_cache.clear()
    state = GameState(level=2, wild_card=None, hands=[[card(rank) for rank in range(2, 14)], [], [], []], turn_index=0)
    calls = []
    def check():
        calls.append(1)
        if len(calls) == 3:
            raise TimeoutError
    with pytest.raises(TimeoutError):
        enumerate_exact_small_hand_patterns(state, 0, check=check)
    assert not _exact_material_cache
    result = search_endgame(state, 0, rng=random.Random(1), deadline=time.perf_counter() - 1)
    assert not result.complete and result.reason == "enumeration_budget_limited" and result.nodes == 0


@pytest.mark.parametrize("level", [2, 14])
@pytest.mark.parametrize("window", [(0.99, 1.0), (0.0, 0.01), (0.45, 0.55)])
def test_bound_cache_research_matches_fresh_full_window(level, window):
    state = GameState(level=level, wild_card=None, hands=[[card(3), card(8)], [card(4)], [card(6)], [card(5)]], turn_index=0, leader=0)
    budget = _Budget(float("inf"), 30000)
    _minimax(state, 0, 24, budget, *window)
    actual = _minimax(state, 0, 24, budget, 0.0, 1.0)
    expected = _minimax(state, 0, 24, _Budget(float("inf"), 30000), 0.0, 1.0)
    assert actual == pytest.approx(expected)
    assert budget.cache and budget.cache_hits > 0


def test_actor_local_endgame_is_not_reported_as_a_solved_information_game():
    from tests.test_team_tactics import human_replay

    state = human_replay(87)
    result = search_endgame(state, state.current_player(), rng=random.Random(11), deadline=float("inf"), information_safe=True)
    assert result.complete and not result.exact
    assert result.continuation == "actor_local_policy"
    assert result.common_samples == 8
    assert outcome_value(state, 0, 0, 2) + outcome_value(state, 1, 0, 2) == pytest.approx(1.0)


@pytest.mark.parametrize("level", [2, 9, 14])
@pytest.mark.parametrize("seat", range(4))
def test_long_hand_guard_preserves_partners_bomb_without_blocking_a_finish(level, seat):
    from tests.test_team_tactics import human_replay

    original = human_replay(10)
    actor = original.current_player()
    state = copy.deepcopy(original)
    state.hands = [original.hands[(s - seat + actor) % 4] for s in range(4)]
    state.turn_index = seat
    state.leader = (original.leader - actor + seat) % 4
    state.level = level
    state.wild_card = Card(level, Suit.HEARTS)
    state.history = [replace(e, player=(e.player - actor + seat) % 4) if isinstance(e, (TurnPlayed, Pass)) else e
                     for e in state.history]
    assert AdvancedStrategy(partner_bomb_guard=True).select_pattern(state, seat) is None
    # Holding only a legal finishing bomb must override partnership restraint.
    state.hands[seat] = [Card(4, suit) for suit in Suit if suit.value < 4]
    action = AdvancedStrategy(partner_bomb_guard=True).select_pattern(state, seat)
    assert action is not None and len(action.cards) == len(state.hands[seat])


def test_statistical_guard_is_not_lowered_by_nonurgent_pass_floor(monkeypatch):
    from guandan.ai.candidates import pattern_key
    from guandan.ai.mcts.information_set import PASS_ACTION, ActionStatistics, SearchResult
    from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy

    state = make_initial_state(level=14, seed=129001)
    state.turn_index = 0
    state.leader = 2
    state.table = [Pattern(PatternType.SINGLE, 3, 1, (card(3),))]
    strategy = DaiChangshengStrategy(mcts_overrides={"time_budget_ms": 0})
    action = AdvancedStrategy().select_pattern(state, 0)
    # Choose a real legal single regardless of the old heuristic's pass choice.
    from guandan.ai.candidates import enumerate_legal_patterns
    action = next(p for p in enumerate_legal_patterns(state, 0) if p.type == PatternType.SINGLE)
    result = SearchResult(action, 12, 6, 0.0, (
        ActionStatistics(PASS_ACTION, None, 6, 6, 0.5, 1.0),
        ActionStatistics(pattern_key(action), action, 6, 6, 0.8, 1.0, PASS_ACTION, 0.2),
    ), common_samples=6)
    monkeypatch.setattr(strategy, "_reference_action", lambda *args: None)
    monkeypatch.setattr("guandan.ai.strategies.professional.root_action_search", lambda *args, **kwargs: result)
    assert strategy.select_pattern(state, 0) is None
    assert strategy.last_guard["required_gain"] == pytest.approx(0.328)
    # A decisive improvement may still justify taking the partner's initiative.
    stronger = replace(result, actions=(result.actions[0], replace(result.actions[1], mean_value=0.9)))
    monkeypatch.setattr("guandan.ai.strategies.professional.root_action_search", lambda *args, **kwargs: stronger)
    assert strategy.select_pattern(state, 0) == action


def test_actor_local_endgame_ignores_real_hidden_cards_and_shuffle_seed():
    from tests.test_team_tactics import human_replay

    state = human_replay(87)
    actor = state.current_player()
    changed = copy.deepcopy(state)
    for seat in range(4):
        if seat != actor:
            changed.hands[seat] = [card(12)] * state.hand_size(seat)
    changed.history = [replace(e, seed=999) if isinstance(e, ShuffleDeal) else e for e in changed.history]
    before = search_endgame(state, actor, rng=random.Random(11), deadline=float("inf"), information_safe=True)
    after = search_endgame(changed, actor, rng=random.Random(11), deadline=float("inf"), information_safe=True)
    assert (before.pattern, before.actions, before.nodes, before.common_samples, before.cache_hits) == (
        after.pattern, after.actions, after.nodes, after.common_samples, after.cache_hits)

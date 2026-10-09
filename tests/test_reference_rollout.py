"""Expert rollout information boundaries, memo equivalence and deadline behavior."""
from __future__ import annotations

import copy
import random
import time
from dataclasses import replace

import pytest

from guandan.ai import rollout_reference
from guandan.ai.mcts.search import simulate_state
from guandan.ai.play import play_or_pass
from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
from guandan.ai.strategies.professional import ProfessionalStrategy
from guandan.ai.strategy import make_strategy
from guandan.engine.card import Card, Suit
from guandan.engine.events import ShuffleDeal
from guandan.engine.state import clone_state_for_search, make_initial_state


@pytest.mark.parametrize("seat", range(4))
@pytest.mark.parametrize("level", [2, 9, 14])
def test_reference_choice_and_memo_ignore_other_cards_and_private_seed(seat, level):
    state = make_initial_state(seed=390001, first_player=seat, level=level)
    changed = copy.deepcopy(state)
    for other in range(4):
        if other != seat:
            changed.hands[other] = [Card(101, Suit.BIG_JOKER)] * state.hand_size(other)
    changed.history = [replace(e, seed=-1) if isinstance(e, ShuffleDeal) else e
                       for e in changed.history]
    assert rollout_reference.reference_key(changed, seat) == rollout_reference.reference_key(state, seat)
    expected = make_strategy(2).select_pattern(state, seat)
    assert rollout_reference.reference_pattern(changed, seat, {}) == expected


@pytest.mark.parametrize("seed", [390002, 390003, 390004])
@pytest.mark.parametrize("reference_turns", [8, 120])
def test_cached_and_uncached_rollouts_have_identical_trajectory_and_value(seed, reference_turns):
    state = make_initial_state(seed=seed)
    for _ in range(24):
        play_or_pass(state, state.current_player(), make_strategy(2), random.Random(1))
    first, second = clone_state_for_search(state), clone_state_for_search(state)
    options = {"rollout_strategy_level": 2, "max_turns": 120, "copy_state": False,
               "reference_rollout_turns": reference_turns}
    memo = {}
    expected = simulate_state(first, state.current_player(), **options)
    actual = simulate_state(second, state.current_player(), reference_memo=memo, **options)
    assert actual == expected and second == first
    third = clone_state_for_search(state)
    assert simulate_state(third, state.current_player(), reference_memo=memo, **options) == expected
    assert third == first and memo


def test_expired_deadline_never_calls_expert(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("expert must not run after the deadline")

    monkeypatch.setattr(rollout_reference, "reference_pattern", forbidden)
    state = make_initial_state(seed=390005)
    before = copy.deepcopy(state)
    value = simulate_state(state, 0, rollout_strategy_level=1, max_turns=120,
                           reference_rollout_turns=8, deadline=time.perf_counter() - 1)
    assert 0 <= value <= 1 and state == before


def test_reference_stage_switches_to_cheap_policy_at_exact_turn(monkeypatch):
    from guandan.ai.mcts import search

    real_cheap = search._rollout_select_pattern
    real_reference = rollout_reference.reference_pattern
    calls = []

    def expert(*args, **kwargs):
        calls.append("expert")
        return real_reference(*args, **kwargs)

    def cheap(*args, **kwargs):
        calls.append("cheap")
        return real_cheap(*args, **kwargs)

    monkeypatch.setattr(rollout_reference, "reference_pattern", expert)
    monkeypatch.setattr(search, "_rollout_select_pattern", cheap)
    simulate_state(make_initial_state(seed=390006), 0, rollout_strategy_level=1,
                   max_turns=6, reference_rollout_turns=3)
    assert calls == ["expert"] * 3 + ["cheap"] * 3


def test_research_override_is_disabled_by_default_and_rejects_incompatible_modes():
    assert ProfessionalStrategy().reference_rollout_turns == 0
    assert DaiChangshengStrategy().reference_rollout_turns == 0
    assert not ProfessionalStrategy().reference_refinement
    assert not DaiChangshengStrategy().reference_refinement
    for options in ({"search_mode": "tree", "reference_rollout_turns": 8},
                    {"reference_rollout_turns": -1}, {"reference_rollout_turns": 41},
                    {"reference_rollout_turns": 8, "partner_adaptation": True},
                    {"reference_rollout_turns": 8, "heterogeneous_rollouts": True}):
        with pytest.raises(ValueError):
            ProfessionalStrategy(**options)


def test_reference_memo_retains_a_cached_pass(monkeypatch):
    state = make_initial_state(seed=390007)
    calls = []

    def pass_policy(*args):
        calls.append(1)
        return None

    monkeypatch.setattr(rollout_reference, "select_heuristic_action", pass_policy)
    memo = {}
    assert rollout_reference.reference_pattern(state, 0, memo) is None
    assert rollout_reference.reference_pattern(state, 0, memo) is None
    assert calls == [1]


@pytest.mark.parametrize("iterations", (48, 768))
def test_refinement_pairs_only_challenger_and_reference_and_replaces_coarse_values(monkeypatch, iterations):
    from guandan.ai.candidates import smallest_legal_pattern
    from guandan.ai.mcts import root_search

    state = make_initial_state(seed=390008)
    reference = smallest_legal_pattern(state, 0)
    assert reference is not None
    reference_size = state.hand_size(0) - len(reference.cards)
    expert_worlds = []

    def value(branch, root, **options):
        if options.get("reference_rollout_turns"):
            expert_worlds.append(tuple(tuple(hand) for hand in branch.hands[1:]))
            return 0.8 if branch.hand_size(root) == reference_size else 0.2
        return 1 - branch.hand_size(root) / 40

    monkeypatch.setattr(root_search, "simulate_state", value)
    result = root_search.root_action_search(state, 0, rng=random.Random(8), iterations=iterations,
        reference_actions=(reference,), reference_refinement=True)
    assert result.reference_refinement["reason"] == "completed"
    assert result.pattern == reference
    assert len(result.actions) == 2
    assert sorted(a.mean_value for a in result.actions) == pytest.approx([0.2, 0.8])
    assert result.simulations <= iterations and 6 <= result.common_samples <= 8
    assert result.reference_refinement["refinement_simulations"] <= 16
    assert result.reference_refinement["max_common_samples"] == 8
    assert len(expert_worlds) >= 12
    for first, second in zip(expert_worlds[::2], expert_worlds[1::2]):
        assert first == second


def test_refinement_with_less_than_six_pairs_returns_reference(monkeypatch):
    from guandan.ai.candidates import smallest_legal_pattern
    from guandan.ai.mcts import root_search

    state = make_initial_state(seed=390009)
    reference = smallest_legal_pattern(state, 0)
    monkeypatch.setattr(root_search, "simulate_state", lambda branch, root, **kw: 1 - branch.hand_size(root) / 40)
    result = root_search.root_action_search(state, 0, rng=random.Random(9), iterations=22,
        reference_actions=(reference,), reference_refinement=True)
    assert result.pattern == reference
    assert result.reference_refinement["reason"] == "insufficient_budget"
    assert result.simulations <= 22


def test_refined_root_scores_ignore_real_hidden_cards_and_private_seed():
    from guandan.ai.mcts.root_search import root_action_search

    state = make_initial_state(seed=390010)
    for _ in range(40):
        play_or_pass(state, state.current_player(), make_strategy(2), random.Random(1))
    actor = state.current_player()
    changed = copy.deepcopy(state)
    for seat in range(4):
        if seat != actor:
            changed.hands[seat] = [Card(3, Suit.CLUBS)] * state.hand_size(seat)
    changed.history = [replace(e, seed=999) if isinstance(e, ShuffleDeal) else e for e in changed.history]
    first = root_action_search(state, actor, rng=random.Random(10), iterations=24, reference_refinement=True)
    second = root_action_search(changed, actor, rng=random.Random(10), iterations=24, reference_refinement=True)
    assert first.pattern == second.pattern
    assert first.actions == second.actions

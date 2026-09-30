"""Trial scoring and isolation must not manufacture an apparent improvement."""
from __future__ import annotations

import copy
import random
from dataclasses import replace
from pathlib import Path

import pytest

from guandan.ai.strategies.advanced import AdvancedStrategy
from guandan.engine.events import ShuffleDeal
from guandan.engine.state import make_initial_state
from guandan.storage.serialization import _dict_to_pattern
from scripts.ai_team_trial import (
    FrozenClient,
    canonical_utility,
    companion_difficulty,
    match_state,
    public_request,
    summarize,
)


def test_worker_request_cannot_reveal_other_cards_or_deal_seed() -> None:
    state = make_initial_state(seed=123)
    before = copy.deepcopy(state)
    request = public_request(state, 0)
    changed = copy.deepcopy(state)
    changed.hands[1], changed.hands[3] = changed.hands[3], changed.hands[1]
    changed.history[0] = replace(changed.history[0], seed=999)
    assert request == public_request(changed, 0)
    assert request["events"][0]["seed"] == 0
    assert request["state"]["ruleset_version"] == 2
    assert "a_failure_counts" not in request["state"]
    assert "a_failure_counts" not in request["events"][0]
    assert request["state"]["hands"][0] != request["state"]["hands"][1]
    assert state == before and isinstance(state.history[0], ShuffleDeal)


def test_frozen_worker_imports_only_its_root_and_matches_unsampled_policy() -> None:
    root = Path(__file__).parents[1]
    client = FrozenClient(root)
    try:
        state = make_initial_state(seed=37)
        request = public_request(state, 0)
        request.update(difficulty=2, mode="fixed", rng_state=random.Random(0).getstate())
        result = client.query(request)
        assert _dict_to_pattern(result["pattern"]) == AdvancedStrategy().select_pattern(state, 0)
    finally:
        client.close()


@pytest.mark.parametrize("level", [2, 9, 14])
@pytest.mark.parametrize("order", [(0, 2, 1), (0, 1, 2), (0, 1, 3), (1, 0, 2)])
def test_trial_utility_is_complementary_and_penalizes_failed_a(level, order) -> None:
    state = make_initial_state(seed=1, level=level)
    state.ruleset_version = 2
    state.finish_order = list(order)
    state.finished = True
    own, other = canonical_utility(state, 0), canonical_utility(state, 1)
    assert own + other == pytest.approx(1.0)
    if level == 14 and order == (0, 1, 3):
        assert own == 0.0


def test_confidence_interval_resamples_whole_swapped_pairs() -> None:
    rows = [{"seed": i, "gain": gain, "head_won": gain > 0, "level": 2,
             "budget_failures": [], "a_succeeded": None}
            for i in range(12) for gain in (1.0, -1.0)]
    result = summarize(rows)
    assert result["pairs"] == 12 and result["games"] == 24
    assert result["gain_confidence_95"] == [0.0, 0.0]
    assert not result["strength_gate_passed"]


def test_parallel_completion_order_does_not_change_bootstrap() -> None:
    rows = [{"seed": i, "gain": ((i % 3) - 1) * 0.2 + leg * 0.03,
             "head_won": bool(i % 2), "level": 2, "budget_failures": [], "a_succeeded": None}
            for i in range(12) for leg in range(2)]
    assert summarize(rows) == summarize(list(reversed(rows)))


def test_mixed_styles_are_balanced_and_not_confounded_with_level() -> None:
    assert [sum(companion_difficulty(i) == style for i in range(60)) for style in range(3)] == [20, 20, 20]
    assert {(i % 3, companion_difficulty(i)) for i in range(60)} == {(level, style) for level in range(3) for style in range(3)}


def test_swapped_pair_keeps_score_and_initiative_fixed():
    for index in range(240):
        assert match_state(index, 0) == match_state(index, 1)
    assert {match_state(i, 0)["first_player"] for i in range(240)} == set(range(4))
    assert {tuple(match_state(i, 0)["a_failure_counts"]) for i in range(240)} >= {(0, 1), (1, 2), (2, 0)}

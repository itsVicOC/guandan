from __future__ import annotations

import random
from dataclasses import FrozenInstanceError, replace

import pytest

from guandan.ai import make_strategy, play_or_pass
from guandan.ai.action_ranker import ActionObservation
from guandan.ai.context import PublicTacticalContext
from guandan.ai.observation import ActorObservation
from guandan.engine.events import ShuffleDeal
from guandan.engine.state import clone_state_for_search, make_initial_state


def test_tactics_and_ranking_share_an_immutable_view_without_hidden_hands_or_seed():
    state = make_initial_state(seed=7)
    rng = random.Random(3)
    for _ in range(10):
        play_or_pass(state, state.current_player(), make_strategy(0), rng)
    actor = state.turn_index
    observation = ActorObservation.from_state(state, actor)
    changed = clone_state_for_search(state)
    for seat in range(4):
        if seat != actor:
            changed.hands[seat].reverse()
    changed.history[0] = replace(changed.history[0], seed=999999)
    assert ActorObservation.from_state(changed, actor) == observation
    assert not hasattr(observation, "hands") and not hasattr(observation, "seed")
    assert not any(isinstance(event, ShuffleDeal) for event in observation.history)
    assert PublicTacticalContext.from_observation(observation) == PublicTacticalContext.from_state(state, actor)
    assert ActionObservation.from_observation(observation) == ActionObservation.from_state(state, actor)
    with pytest.raises(FrozenInstanceError):
        observation.player = 3

from __future__ import annotations

import random

from guandan.ai import make_strategy, play_or_pass
from guandan.ai.mcts.root_search import root_action_search
from guandan.ai.tactics import select_heuristic_action
from guandan.engine.state import make_initial_state


def test_paired_samples_are_distinguished_from_terminal_worlds():
    state = make_initial_state(seed=7)
    result = root_action_search(state, state.turn_index, rng=random.Random(1), iterations=24,
                                rollout_max_turns=1)
    assert result.common_samples > 0
    assert result.terminal_common_samples == result.terminal_rollouts == 0
    assert result.cutoff_rollouts == result.simulations == 24
    assert result.discarded_rollouts == 0


def test_short_endgame_records_terminal_pairs_and_paired_uncertainty():
    state = make_initial_state(seed=7)
    rng = random.Random(1)
    policy = make_strategy(0)
    while not state.finished and sum(map(len, state.hands)) > 8:
        play_or_pass(state, state.current_player(), policy, rng)
    assert not state.finished
    actor = state.turn_index
    result = root_action_search(state, actor, rng=random.Random(1), iterations=24, rollout_max_turns=1000,
                                reference_actions=(select_heuristic_action(state, actor, 2),))
    assert result.common_samples >= 2
    assert result.terminal_common_samples == result.common_samples
    assert result.terminal_rollouts == result.simulations == 24 and result.cutoff_rollouts == 0
    assert all(action.paired_standard_error is not None for action in result.actions)

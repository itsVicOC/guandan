"""Strict event-stream replay regressions."""
from __future__ import annotations

import random

import pytest

from guandan.ai import make_strategy
from guandan.ai.play import play_or_pass
from guandan.engine.events import Pass, TributeResisted
from guandan.engine.replay import replay_events
from guandan.engine.state import make_initial_state
from guandan.ui.replay import ReplayCursor


def _completed_game(seed: int = 9):
    state = make_initial_state(level=2, first_player=0, seed=seed)
    strategy = make_strategy(0)
    rng = random.Random(seed)
    for _ in range(2000):
        if state.finished:
            break
        play_or_pass(state, state.turn_index, strategy, rng)
    assert state.finished
    return state


def test_complete_event_stream_replays_exactly() -> None:
    state = _completed_game()
    assert replay_events(state.history) == state


def test_unseeded_deal_records_the_resolved_seed_for_exact_replay() -> None:
    state = make_initial_state(level=2, first_player=0, seed=None)

    assert state.history[0].seed != 0
    assert replay_events(state.history) == state


def test_complete_replay_rejects_omitted_engine_events_but_prefix_allows_them() -> None:
    state = _completed_game()
    truncated = state.history[:-1]

    with pytest.raises(ValueError, match="omits engine-emitted events"):
        replay_events(truncated)

    prefix_state = replay_events(truncated, allow_incomplete_tail=True)
    assert prefix_state.finished


def test_replay_rejects_events_after_game_over() -> None:
    state = _completed_game()
    extra = Pass(player=0, hand_remaining=0)

    with pytest.raises(ValueError, match="after GameOver"):
        replay_events([*state.history, extra])


def test_replay_rejects_tribute_after_gameplay_started() -> None:
    state = make_initial_state(level=2, first_player=0, seed=4)
    strategy = make_strategy(0)
    play_or_pass(state, 0, strategy, random.Random(4))
    invalid = [
        *state.history,
        TributeResisted(player=1, team=1, reason="late"),
    ]

    with pytest.raises(ValueError, match="before gameplay"):
        replay_events(invalid)


def test_replay_cursor_precomputes_exact_event_states() -> None:
    state = _completed_game()
    cursor = ReplayCursor(state.history)

    assert len(cursor.states) == len(state.history)
    assert cursor.state.hands == state.hands
    assert cursor.state.finish_order == state.finish_order
    assert cursor.state.history == []
    cursor.set_index(0)
    assert sum(len(hand) for hand in cursor.state.hands) == 108
    assert cursor.state.history == []
    assert cursor.set_index(10_000) == len(state.history) - 1
    assert cursor.state.hands == state.hands

"""Strict event-stream replay regressions."""
from __future__ import annotations

import random

import pytest

from guandan.ai import make_strategy
from guandan.ai.play import play_or_pass
from guandan.engine.events import Pass, TributeResisted
from guandan.engine.replay import replay_events
from guandan.engine.rules.patterns import find_complete_pattern
from guandan.engine.state import IllegalPlayError, make_initial_state, pass_turn, play_pattern
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


def test_legacy_pass_lockout_stream_replays_with_its_original_ruleset() -> None:
    state = make_initial_state(level=5, first_player=2, seed=42, ruleset_version=1)
    west_card = min(state.hands[2], key=lambda card: card.rank)
    west_play = find_complete_pattern([west_card], state.wild_card)
    assert west_play is not None
    north_play = next(
        pattern
        for card in state.hands[3]
        if (pattern := find_complete_pattern([card], state.wild_card)) is not None
        and pattern.can_be_played_on(west_play, level=state.level)
    )

    play_pattern(state, 2, west_play)
    pass_turn(state, 1)
    pass_turn(state, 0)
    play_pattern(state, 3, north_play)
    pass_turn(state, 2)
    assert state.turn_index == 3
    assert state.table == []
    next_play = find_complete_pattern([state.hands[3][0]], state.wild_card)
    assert next_play is not None
    play_pattern(state, 3, next_play)

    assert replay_events(state.history, ruleset_version=1) == state
    assert ReplayCursor(state.history, ruleset_version=1).state.hands == state.hands
    with pytest.raises(IllegalPlayError, match="not player's turn"):
        replay_events(state.history, ruleset_version=2)

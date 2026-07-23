"""Event replay for rebuilding a game state from its persisted event stream."""
from __future__ import annotations

import copy
from collections.abc import Sequence

from .card import Card
from .events import (
    Claim,
    Drift,
    Event,
    GameOver,
    LevelUp,
    Pass,
    ShuffleDeal,
    TributeResisted,
    TributeReturned,
    TributeSent,
    TurnPlayed,
)
from .state import GameState, IllegalPlayError, claim, make_initial_state, pass_turn, play_pattern


def replay_events(
    events: Sequence[Event],
    *,
    allow_incomplete_tail: bool = False,
) -> GameState:
    """Rebuild a state from a complete, ordered event stream.

    A saved snapshot is only a cache. This function is the compatibility path
    for snapshot-less saves and deliberately validates every state-changing
    event while applying it.
    """
    state, _ = _replay_events(events, allow_incomplete_tail=allow_incomplete_tail)
    return state


def replay_event_states(events: Sequence[Event]) -> tuple[GameState, ...]:
    """Build one immutable-by-convention state snapshot per persisted event."""
    _, states = _replay_events(events, allow_incomplete_tail=False, capture_states=True)
    return tuple(states)


def _replay_events(
    events: Sequence[Event],
    *,
    allow_incomplete_tail: bool,
    capture_states: bool = False,
) -> tuple[GameState, list[GameState]]:
    if not events or not isinstance(events[0], ShuffleDeal):
        raise ValueError("event stream must start with ShuffleDeal")

    shuffle = events[0]
    state = make_initial_state(
        level=shuffle.level,
        first_player=shuffle.first_player,
        seed=shuffle.seed,
        team_levels=shuffle.team_levels,
    )
    states = [_snapshot_state(state)] if capture_states else []
    confirmed_history_length = 1
    gameplay_started = False
    for event in events[1:]:
        if confirmed_history_length < len(state.history):
            if state.history[confirmed_history_length] != event:
                raise ValueError("event stream does not match engine-emitted events")
            confirmed_history_length += 1
            if capture_states:
                states.append(_snapshot_state(state))
            continue
        if state.finished:
            raise ValueError("event stream contains events after GameOver")
        if isinstance(event, (TurnPlayed, Pass, Claim)):
            gameplay_started = True
        elif gameplay_started and isinstance(
            event, (TributeSent, TributeReturned, TributeResisted)
        ):
            raise ValueError("tribute events must occur before gameplay")
        _apply_replay_event(state, event)
        if (
            confirmed_history_length >= len(state.history)
            or state.history[confirmed_history_length] != event
        ):
            raise ValueError("event does not match replayed state")
        confirmed_history_length += 1
        if capture_states:
            states.append(_snapshot_state(state))
    if not allow_incomplete_tail and confirmed_history_length != len(state.history):
        raise ValueError("event stream omits engine-emitted events")
    return state, states


def _snapshot_state(state: GameState) -> GameState:
    snapshot = copy.deepcopy(state)
    # Timeline rendering only needs current state. Retaining every prefix's
    # history would make the cache quadratic in the event count.
    snapshot.history = []
    return snapshot


def _apply_replay_event(state: GameState, event: Event) -> None:
    if isinstance(event, TurnPlayed):
        play_pattern(state, event.player, event.pattern)
        return

    if isinstance(event, Pass):
        pass_turn(state, event.player)
        return

    if isinstance(event, Claim):
        try:
            claim(state, event.player, event.count)
        except IllegalPlayError as exc:
            raise ValueError("Claim event does not match replayed state") from exc
        return

    if isinstance(event, (TributeSent, TributeReturned)):
        _move_tribute_card(state, event.from_player, event.to_player, event.card)
        state.history.append(event)
        return

    if isinstance(event, TributeResisted):
        state.history.append(event)
        return

    if isinstance(event, Drift):
        state.drift = True
        state.history.append(event)
        return

    if isinstance(event, (LevelUp, GameOver)):
        raise ValueError(f"{type(event).__name__} must be emitted by terminal play")

    if isinstance(event, ShuffleDeal):
        raise ValueError("ShuffleDeal is only valid as the first event")

    raise ValueError(f"unsupported event: {type(event).__name__}")


def _move_tribute_card(state: GameState, from_player: int, to_player: int, card: Card) -> None:
    if not 0 <= from_player < 4 or not 0 <= to_player < 4:
        raise ValueError("tribute event has an invalid player")
    if card not in state.hands[from_player]:
        raise ValueError("tribute card is not in the source hand")
    state.hands[from_player].remove(card)
    state.hands[to_player].append(card)


__all__ = ["replay_event_states", "replay_events"]

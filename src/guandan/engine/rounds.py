"""Shared cross-round state inheritance and dealt-round event updates."""
from __future__ import annotations

from dataclasses import replace

from .events import ShuffleDeal, TributeResisted, TributeReturned, TributeSent
from .state import GameState, make_initial_state


def deal_next_round(previous: GameState, *, seed: int, first_player: int) -> GameState:
    if not previous.finished or previous.match_finished:
        raise ValueError("previous state must be a completed non-final round")
    levels = previous.team_levels_final or previous.team_levels
    level = levels[previous.finish_order[0] % 2] if previous.team_levels_final and previous.finish_order else previous.level
    return make_initial_state(
        level=level, first_player=first_player, seed=seed, team_levels=levels,
        ruleset_version=previous.ruleset_version, a_failure_counts=previous.a_failure_counts,
    )


def set_dealt_round_starter(state: GameState, first_player: int) -> None:
    """Set the tribute winner without dropping fields from the deal event."""
    if first_player not in range(4):
        raise ValueError("first player must be a seat from 0 to 3")
    has_deal = bool(state.history and isinstance(state.history[0], ShuffleDeal))
    if any(not isinstance(event, (TributeSent, TributeReturned, TributeResisted))
           for event in (state.history[1:] if has_deal else state.history)):
        raise ValueError("cannot change the starter after gameplay")
    # Small actor/UI fixtures may deliberately have no reproducible deal.
    if has_deal:
        assert isinstance(state.history[0], ShuffleDeal)
        state.history[0] = replace(state.history[0], first_player=first_player)
    state.turn_index = state.leader = first_player

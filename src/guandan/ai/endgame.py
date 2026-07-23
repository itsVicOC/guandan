"""Shared short-hand and immediate-finish decision helpers."""
from __future__ import annotations

from ..engine.hand import Pattern
from ..engine.rules.patterns import find_complete_pattern
from ..engine.state import GameState


def legal_finish_pattern(state: GameState, player: int) -> Pattern | None:
    """Return the only move that sheds the player's entire hand, if legal."""
    hand = state.hands[player]
    if not hand:
        return None
    pattern = find_complete_pattern(hand, state.wild_card)
    if pattern is None:
        return None
    if state.table and not pattern.can_be_played_on(state.table[-1], level=state.level):
        return None
    return pattern


__all__ = ["legal_finish_pattern"]

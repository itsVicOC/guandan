"""AI decision context helpers."""
from __future__ import annotations

from ..engine.state import GameState, is_teammate


def opponent_hand_sizes(state: GameState, player: int) -> list[int]:
    """Active opponents' hand sizes, excluding finished players."""
    return [
        state.hand_size(p)
        for p in range(4)
        if not is_teammate(p, player) and state.hand_size(p) > 0
    ]


def opponent_min_cards(state: GameState, player: int) -> int:
    """Minimum active opponent hand size; 0 when no opponent is active."""
    return min(opponent_hand_sizes(state, player), default=0)


def opponent_has_one_card(state: GameState, player: int) -> bool:
    """Whether any active opponent is down to one card."""
    return opponent_min_cards(state, player) == 1

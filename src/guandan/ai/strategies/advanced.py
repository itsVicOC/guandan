"""Public-memory hand planning and context-aware partnership tactics."""
from __future__ import annotations

from ...engine.hand import Pattern
from ...engine.state import GameState, is_teammate
from ...engine.trick import current_top_player
from ..tactics import select_heuristic_action


def _teammate_winning(state: GameState, player: int) -> bool:
    """Whether a partner currently owns the trick (a signal, not a pass rule)."""
    top = current_top_player(state)
    return bool(state.table and top is not None and is_teammate(top, player))


class AdvancedStrategy:
    name = "高手"
    difficulty = 2
    uses_stochastic_pass = False

    def select_pattern(self, state: GameState, player: int) -> Pattern | None:
        return select_heuristic_action(state, player, 2)

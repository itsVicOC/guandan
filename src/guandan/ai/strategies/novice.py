"""档 0 新手策略：基础理牌和清晰的过牌判断。"""
from __future__ import annotations

from ...engine.hand import Pattern
from ...engine.state import GameState
from ..tactics import select_heuristic_action


class NoviceStrategy:
    """新手 AI：不记牌、不搜索，保留明显有用的炸弹。"""

    name = "新手"
    difficulty = 0
    uses_stochastic_pass = False

    def select_pattern(
        self, state: GameState, player: int
    ) -> Pattern | None:
        return select_heuristic_action(state, player, 0)

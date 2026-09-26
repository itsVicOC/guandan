"""档 1 进阶策略：使用有界剩余牌组规划。"""
from __future__ import annotations

from ...engine.hand import Pattern
from ...engine.state import GameState
from ..tactics import select_heuristic_action


class IntermediateStrategy:
    """进阶 AI：比较出牌后剩余手数和控制牌消耗。"""

    name = "进阶"
    difficulty = 1
    uses_stochastic_pass = False

    def select_pattern(
        self, state: GameState, player: int
    ) -> Pattern | None:
        return select_heuristic_action(state, player, 1)

"""档 0 新手策略：纯贪心 + 概率过牌。"""
from __future__ import annotations

from ...engine.hand import Pattern
from ...engine.state import GameState
from ..endgame import legal_finish_pattern
from ..greedy import select_min_winning


class NoviceStrategy:
    """新手 AI：调 `greedy.select_min_winning` 出最小可压，概率过牌（不估值、不记牌）。"""

    name = "新手"
    difficulty = 0
    uses_stochastic_pass = True

    def select_pattern(
        self, state: GameState, player: int
    ) -> Pattern | None:
        finish = legal_finish_pattern(state, player)
        if finish is not None:
            return finish
        return select_min_winning(state, player)

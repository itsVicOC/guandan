"""档 0 新手策略：纯贪心 + 概率过牌。"""
from __future__ import annotations

from ...engine.hand import Pattern
from ...engine.state import GameState
from ..greedy import select_min_winning


class NoviceStrategy:
    """新手 AI：调 `greedy.select_min_winning` 出最小可压，概率过牌（不估值、不记牌）。"""

    name = "新手"
    difficulty = 0

    def select_pattern(
        self, state: GameState, player: int
    ) -> Pattern | None:
        return select_min_winning(state, player)

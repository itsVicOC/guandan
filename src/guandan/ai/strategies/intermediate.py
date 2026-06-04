"""档 1 进阶策略：贪心 + 简单估值。

在多个候选牌型里选 `estimate_pattern_cost` 最小的那手，避免拆对/拆王/浪费 wild。
"""
from __future__ import annotations

from ...engine.hand import Pattern
from ...engine.state import GameState
from ..greedy import select_min_winning
from ..valuation import enumerate_candidate_plays


class IntermediateStrategy:
    """进阶 AI：枚举 top-K 候选出牌，按估值升序选。"""

    name = "进阶"
    difficulty = 1

    def select_pattern(
        self, state: GameState, player: int
    ) -> Pattern | None:
        candidates = enumerate_candidate_plays(state, player, max_candidates=5)
        if candidates:
            return candidates[0]
        # 兜底：贪心
        return select_min_winning(state, player)

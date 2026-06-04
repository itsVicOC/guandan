"""档 2 高手策略：贪心 + 记牌 + 协作分。

- 队友已领先 → 主动过牌（让队友收这一轮）
- 估值时考虑记牌（哪些 rank 已绝张/还剩几张）
- 用更小的过牌概率（强手时更不舍得打）
"""
from __future__ import annotations

from typing import Optional

from ...engine.hand import Pattern
from ...engine.state import GameState, is_teammate, partner_of
from ..memory import PlayedTracker
from ..valuation import enumerate_candidate_plays, estimate_pattern_cost
from ..greedy import select_min_winning


def _teammate_winning(state: GameState, player: int) -> bool:
    """队友是否正在"领牌"（是本轮最后一个出牌的玩家）。"""
    # 队友领牌 = 队友是 table 上最后一个出牌的玩家
    if not state.table:
        return False
    last_turn = state.table[-1]
    # 从 history 找 last_turn 的出牌者
    from ...engine.events import TurnPlayed

    for ev in reversed(state.history):
        if isinstance(ev, TurnPlayed) and ev.pattern is last_turn:
            return is_teammate(ev.player, player)
    return False


def _key_count_exhausted(state: GameState, player: int, candidate: Pattern) -> bool:
    """出完这张牌后，关键 rank 在其他 3 家手里是否绝张。"""
    hand = state.hands[player]
    tracker = PlayedTracker.from_history(state)
    # 关注 candidate 里所有 rank
    for c in candidate.cards:
        others = tracker.in_someone_hand(c.rank, hand)
        my_count_after = sum(
            1 for x in hand if x.rank == c.rank
        ) - sum(1 for x in candidate.cards if x.rank == c.rank)
        if my_count_after == 0 and others == 0:
            return True
    return False


class AdvancedStrategy:
    """高手 AI：协作分 + 记牌 + 估值。"""

    name = "高手"
    difficulty = 2

    def select_pattern(
        self, state: GameState, player: int
    ) -> Optional[Pattern]:
        # 协作：队友已领先 → 让队友收这一轮
        if _teammate_winning(state, player):
            return None

        # 估值候选
        candidates = enumerate_candidate_plays(state, player, max_candidates=5)
        if not candidates:
            return select_min_winning(state, player)

        # 记牌加成：如果 candidate 出完后某 rank 绝张（自己+其他家都没了），
        # 估值大幅降低（鼓励出 → 防止对方绝张反过来压）
        scored: list[tuple[float, Pattern]] = []
        for c in candidates:
            cost = estimate_pattern_cost(state, player, c)
            if _key_count_exhausted(state, player, c):
                cost -= 10.0
            scored.append((cost, c))
        scored.sort(key=lambda t: t[0])
        return scored[0][1]

"""记牌器（card counting）。

从 `state.history` 推出"哪些牌已经出过"，给档 2 估值用。
"""
from __future__ import annotations

from typing import Dict, List, Set

from ..engine.card import (
    NORMAL_MAX,
    NORMAL_MIN,
    RANK_BIG_JOKER,
    RANK_SMALL_JOKER,
)
from ..engine.events import Pass, TurnPlayed
from ..engine.state import GameState


class PlayedTracker:
    """已经出过的牌（按 rank 统计）。"""

    def __init__(self) -> None:
        # 已出张数（每种 rank 出了多少张）
        self.played_by_rank: Dict[int, int] = {}
        # 已出牌型分类
        self.bomb_count: int = 0
        # 出过 Pass 的玩家（信息量小，但可推断"他没什么好压的"）
        self.passers: Set[int] = set()

    @classmethod
    def from_history(cls, state: GameState) -> "PlayedTracker":
        t = cls()
        for ev in state.history:
            if isinstance(ev, TurnPlayed):
                for c in ev.pattern.cards:
                    t.played_by_rank[c.rank] = t.played_by_rank.get(c.rank, 0) + 1
                from ..engine.hand import PatternType

                if ev.pattern.type in (
                    PatternType.BOMB,
                    PatternType.STRAIGHT_FLUSH,
                    PatternType.FOUR_JOKERS,
                ):
                    t.bomb_count += 1
            elif isinstance(ev, Pass):
                t.passers.add(ev.player)
        return t

    def remaining(self, rank: int) -> int:
        """某种 rank 还剩几张（未出）= 总数 - 已出。"""
        if rank == RANK_SMALL_JOKER or rank == RANK_BIG_JOKER:
            total = 2
        elif NORMAL_MIN <= rank <= NORMAL_MAX:
            total = 4  # 2 副牌，每种 rank 4 张
        else:
            return 0
        return max(0, total - self.played_by_rank.get(rank, 0))

    def is_exhausted(self, rank: int) -> bool:
        """某种 rank 是否已经绝张（全部被打出或在我自己手里？仅看"打出"）。"""
        # 绝张 = 总数 - 我手牌 - 已出 = 0
        # 此方法只看"已出"，需要结合手牌判断
        return self.remaining(rank) == 0

    def in_someone_hand(self, rank: int, my_hand: List[object]) -> int:
        """某种 rank 在其他 3 家手里还剩几张（不含我自己）。"""
        my_count = sum(1 for c in my_hand if c.rank == rank)
        return max(0, self.remaining(rank) - my_count)

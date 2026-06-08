"""进贡 / 还贡 / 抗贡。

流程（简化版）：
1. 触发条件：一局结束，下游方进贡给上游方
2. 进贡方选择手牌中最大的牌（含王），交给上游
3. 上游还一张点数 ≤ 10 的牌
4. 抗贡：进贡方手牌含 大王×2 + 小王×2，可拒绝进贡
5. 进 / 还贡后：从进贡方起牌
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..card import (
    RANK_10,
    Card,
)


def can_resist_tribute(hand: List[Card]) -> bool:
    """是否可抗贡（手牌含 大王×2 + 小王×2）。"""
    big = sum(1 for c in hand if c.is_big_joker)
    small = sum(1 for c in hand if c.is_small_joker)
    return big >= 2 and small >= 2


def select_tribute_card(hand: List[Card]) -> Card:
    """选择进贡的牌：手牌中最大的牌。"""
    return max(hand)


def can_return_tribute(card: Card) -> bool:
    """检查一张牌是否可以作为还贡（点数 ≤ 10，不含王）。"""
    if card.is_joker:
        return False
    return card.rank <= RANK_10


def select_return_card(hand: List[Card]) -> Card:
    """选择还贡的牌：点数 ≤ 10 的最小牌。"""
    candidates = [c for c in hand if can_return_tribute(c)]
    if not candidates:
        # 找不到合适的牌（极端情况）→ 还最小的
        return min(hand)
    return min(candidates)


@dataclass
class TributeResult:
    """进贡/还贡结果。"""

    resisted: bool
    tribute_card: Optional[Card]  # 进贡的牌
    return_card: Optional[Card]  # 还贡的牌
    first_player_after: int  # 进 / 还贡后下一轮先手


def resolve_tribute(
    upstream: int,
    downstream: int,
    upstream_hand: List[Card],
    downstream_hand: List[Card],
) -> TributeResult:
    """执行进 / 还贡流程。返回结果，调用方负责实际修改手牌。"""
    if can_resist_tribute(downstream_hand):
        return TributeResult(
            resisted=True,
            tribute_card=None,
            return_card=None,
            first_player_after=downstream,
        )

    tribute = select_tribute_card(downstream_hand)
    remaining_upstream = [*list(upstream_hand), tribute]

    return_card = select_return_card(remaining_upstream)

    # 进 / 还贡后：从进贡方起牌（downstream）
    return TributeResult(
        resisted=False,
        tribute_card=tribute,
        return_card=return_card,
        first_player_after=downstream,
    )

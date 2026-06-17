"""进贡 / 还贡 / 抗贡。

流程（简化版）：
1. 触发条件：一局结束，下游方进贡给上游方
2. 进贡方选择手牌中最大的牌（含王），交给上游
3. 上游还一张点数 ≤ 10 的牌
4. 抗贡：进贡方手牌含 大王×2 + 小王×2，可拒绝进贡
5. 进 / 还贡后：单贡由末游起牌；双贡比较三游、末游进贡牌，贡大者起牌
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


def compare_tribute_cards(left: Card, right: Card) -> int:
    """比较两张进贡牌大小。

    返回 1 表示 left 大，-1 表示 right 大，0 表示完全相同。这里复用
    Card 的稳定排序：王 > A > ... > 2，同点数时按既有花色顺序兜底。
    """
    if left > right:
        return 1
    if left < right:
        return -1
    return 0


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


def next_round_first_player_after_tribute(
    finish_order: list[int],
    next_hands: list[list[Card]],
) -> int:
    """根据上局名次和新局进贡牌确定下一局先手。

    - 三游和末游不同队：末游单贡，末游先手。
    - 三游和末游同队：三游、末游双贡，比较两人的进贡牌，贡大者先手。
    - 进贡牌完全相同时，采用末游先手作为稳定兜底。
    """
    if len(finish_order) < 3:
        return finish_order[0] if finish_order else 0

    third = finish_order[2]
    last = next(player for player in range(4) if player not in finish_order)
    if third % 2 != last % 2:
        return last
    if len(next_hands) <= max(third, last) or not next_hands[third] or not next_hands[last]:
        return last

    third_tribute = select_tribute_card(next_hands[third])
    last_tribute = select_tribute_card(next_hands[last])
    comparison = compare_tribute_cards(third_tribute, last_tribute)
    if comparison > 0:
        return third
    return last


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

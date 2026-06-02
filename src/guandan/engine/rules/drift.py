"""漂牌规则。

上游方在出过 A 之后，若最后一手出 5 张及以上级牌组成的炸弹（或更大的牌型），视为漂。
漂后下局级数再额外升 3 级。
"""
from __future__ import annotations

from typing import List

from ..card import Card
from ..hand import Pattern, PatternType


def is_drift_pattern(pattern: Pattern, level: int) -> bool:
    """判断一个牌型是否是"漂牌"（上游最后一手）。"""
    if pattern.type != PatternType.BOMB:
        return False
    if pattern.length < 5:
        return False
    # 全部由级牌组成
    return all(c.rank == level for c in pattern.cards)


def has_played_ace_this_game(history_cards_played: List[Card]) -> bool:
    """检查本局是否出过 A。"""
    for c in history_cards_played:
        if not c.is_joker and c.rank == 14:  # RANK_A
            return True
    return False

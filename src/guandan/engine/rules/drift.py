"""漂牌兼容接口。

当前项目不启用漂牌扩展玩法。保留本模块是为了兼容旧调用和旧存档
schema，但任何牌型都不会触发额外升级。
"""
from __future__ import annotations

from typing import List

from ..card import Card
from ..hand import Pattern


def is_drift_pattern(pattern: Pattern, level: int) -> bool:
    """兼容旧接口：漂牌扩展玩法已禁用，始终返回 False。"""
    return False


def has_played_ace_this_game(history_cards_played: List[Card]) -> bool:
    """兼容旧接口：检查历史出牌中是否出现过 A。"""
    return any(not c.is_joker and c.rank == 14 for c in history_cards_played)  # RANK_A

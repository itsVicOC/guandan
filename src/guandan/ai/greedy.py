"""贪心出牌选择：找"刚好压过桌顶的最小牌型"。"""
from __future__ import annotations

from typing import Optional

from ..engine.hand import Pattern
from ..engine.state import GameState
from .candidates import smallest_legal_pattern


def select_min_winning(state: GameState, player: int) -> Optional[Pattern]:
    """为 player 找最小可压牌型。

    行为：
    - table 空（leader）→ 出当前最小合法牌型
    - 有桌顶牌 → 优先出同型同长度的最小可压牌
    - 同型压不了 → 找最小炸弹类牌型
    """
    return smallest_legal_pattern(state, player)

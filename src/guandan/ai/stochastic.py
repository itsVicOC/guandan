"""概率过牌。

从 `cli._ai_play` 抽出来的"是否主动过牌"逻辑。注入 `rng` 让测试可 seed。
"""
from __future__ import annotations

import random
from typing import Optional

from ..engine.card import RANK_A
from ..engine.hand import Pattern
from ..engine.state import GameState


def should_pass(
    state: GameState,
    player: int,
    pattern: Optional[Pattern],
    *,
    rng: random.Random,
    base: float = 0.10,
    scale: float = 0.60,
) -> bool:
    """给一个能压的牌型，按"出牌越大越舍不得"原则概率过牌。

    概率范围：`[base, base+scale]`——越大的牌型越倾向过牌。
    默认 base=0.10, scale=0.60 → 概率范围 `[0.10, 0.70]`。
    """
    if pattern is None:
        return True  # 找不到牌型 → 一定过
    table_top = state.table[-1] if state.table else None
    if table_top is None:
        return False  # leader 必须出

    rank = table_top.rank
    # 桌顶是王 → 当作 A 顶
    if rank > RANK_A:
        rank = RANK_A

    p = base + (rank - 2) / (RANK_A - 2) * scale
    return rng.random() < p

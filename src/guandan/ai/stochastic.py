"""概率过牌。

从 `cli._ai_play` 抽出来的"是否主动过牌"逻辑。注入 `rng` 让测试可 seed。
"""
from __future__ import annotations

import random
from typing import Optional

from ..engine.card import RANK_A
from ..engine.hand import Pattern, PatternType
from ..engine.state import GameState, is_teammate
from ..engine.trick import current_top_player


def _is_bomb(pattern: Pattern) -> bool:
    return pattern.type in (
        PatternType.BOMB,
        PatternType.STRAIGHT_FLUSH,
        PatternType.FOUR_JOKERS,
    )


def _opponent_min_cards(state: GameState, player: int) -> int:
    sizes = [
        state.hand_size(p)
        for p in range(4)
        if not is_teammate(p, player) and state.hand_size(p) > 0
    ]
    return min(sizes, default=0)


def should_pass(
    state: GameState,
    player: int,
    pattern: Optional[Pattern],
    *,
    rng: random.Random,
    base: float = 0.10,
    scale: float = 0.60,
    multiplier: float = 1.0,
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
    if len(pattern.cards) == state.hand_size(player):
        return False  # 能一手走完就不随机过牌

    rank = table_top.rank
    # 桌顶是王 → 当作 A 顶
    if rank > RANK_A:
        rank = RANK_A

    p = base + (rank - 2) / (RANK_A - 2) * scale

    # 队友正在领牌时更愿意让队友收轮；对手快出完时更愿意出手拦截。
    top_player = current_top_player(state)
    if top_player is not None and is_teammate(top_player, player):
        p += 0.20

    opponent_min = _opponent_min_cards(state, player)
    if 0 < opponent_min <= 2:
        p *= 0.25
    elif 0 < opponent_min <= 5:
        p *= 0.60

    # 炸弹类响应更昂贵，默认更谨慎；非炸弹结构牌略微鼓励打出去整理手牌。
    if _is_bomb(pattern):
        p += 0.20
    elif pattern.type in (
        PatternType.STRAIGHT,
        PatternType.PAIR_SEQUENCE,
        PatternType.TRIPLE_SEQUENCE,
        PatternType.TRIPLE_PAIR,
    ):
        p -= 0.05

    p = max(0.0, min(0.95, p * multiplier))
    return rng.random() < p

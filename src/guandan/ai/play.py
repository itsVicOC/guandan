"""AI 行动：把"策略选牌 + 概率过牌 + 出牌/过牌"打包成一个可复用的动作。

CLI 和 TUI 都通过 `play_or_pass` 调 AI，避免重复决策逻辑。
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ..engine.rules.patterns import find_complete_pattern
from ..engine.state import IllegalPlayError, pass_turn, play_pattern
from .stochastic import should_pass

if TYPE_CHECKING:
    from ..engine.state import GameState
    from .strategy import AIStrategy


def play_or_pass(
    state: GameState,
    player: int,
    strategy: AIStrategy,
    rng: random.Random,
) -> bool:
    """AI 玩家 player 行动：返回 True 出牌，False 过牌。

    决策流程：
    1. `strategy.select_pattern(state, player)` 决定出哪手
       - 返回 None：策略选择"不出"（找不到能压 / 协作分让队友收）
    2. leader（table 空）→ 必须出
    3. 找到牌型 → 概率过牌（避免 AIs 100% 压让真人被无限卡住）

    `rng` 注入是为了让测试可 seed。CLI 用 `random.Random(args.seed)`；
    TUI 用未 seed 的 `random.Random()`（系统熵）。
    """
    if state.turn_index != player or state.finished:
        return False
    p = strategy.select_pattern(state, player)
    if p is None:
        # 策略决定不出 → 尝试过牌
        try:
            pass_turn(state, player)
        except IllegalPlayError:
            # 是 leader 时不能过牌 → 兜底出最小非 wild 单张
            hand = state.hands[player]
            if hand:
                fallback_card = min(
                    (c for c in hand if c != state.wild_card),
                    key=lambda c: c.rank,
                    default=hand[0],
                )
                fallback = find_complete_pattern([fallback_card], state.wild_card)
                if fallback is not None:
                    play_pattern(state, player, fallback)
        return False
    if not state.table:
        # leader 模式 → 必须出
        play_pattern(state, player, p)
        return True
    if should_pass(state, player, p, rng=rng):
        pass_turn(state, player)
        return False
    play_pattern(state, player, p)
    return True

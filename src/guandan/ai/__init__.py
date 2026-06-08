"""AI 策略包。

M2 提供：
- 3 档可玩的 AI 策略（`make_strategy(0|1|2)`）
- `AIStrategy` Protocol（外部实现档 3/4 时遵循）
- 共享的贪心选择 / 估值 / 记牌 / 概率过牌 工具
- `play_or_pass(state, player, strategy, rng)` 出牌/过牌的统一动作（CLI + TUI 复用）
- `AINotImplementedError`（档 3/4 阻断）
- `DIFFICULTY_NAMES`（档位 → 人类可读名）
"""
from __future__ import annotations

from .play import play_or_pass
from .strategy import (
    DIFFICULTY_NAMES,
    AINotImplementedError,
    AIStrategy,
    make_strategy,
)

__all__ = [
    "DIFFICULTY_NAMES",
    "AINotImplementedError",
    "AIStrategy",
    "make_strategy",
    "play_or_pass",
]

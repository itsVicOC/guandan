"""AI 策略包。

提供 5 档 AI（索引 0-4：新手 / 进阶 / 高手 / 职业 / 戴长胜）：
- 档 0/1/2 为贪心 + 估值 + 记牌
- 档 3/4 为团队感知 SO-ISMCTS（`ai/mcts/information_set.py`）
- `AIStrategy` Protocol 供外部实现遵循
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

"""3 档 AI 策略实现。

- NoviceStrategy（档 0 新手）：纯贪心 + 弱记牌
- IntermediateStrategy（档 1 进阶）：贪心 + 简单估值
- AdvancedStrategy（档 2 高手）：贪心 + 记牌 + 协作分
"""
from __future__ import annotations

from .novice import NoviceStrategy
from .intermediate import IntermediateStrategy
from .advanced import AdvancedStrategy

__all__ = ["NoviceStrategy", "IntermediateStrategy", "AdvancedStrategy"]

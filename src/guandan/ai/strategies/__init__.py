"""档 0/1/2 的快速策略实现。

- NoviceStrategy（档 0 新手）：纯贪心 + 弱记牌
- IntermediateStrategy（档 1 进阶）：贪心 + 简单估值
- AdvancedStrategy（档 2 高手）：贪心 + 记牌 + 协作分

档 3/4 也复用这里的 AdvancedStrategy 作为搜索不可用时的快速路径，
因此本模块不是"全部 5 档"的实现。
"""
from __future__ import annotations

from .advanced import AdvancedStrategy
from .intermediate import IntermediateStrategy
from .novice import NoviceStrategy

__all__ = ["AdvancedStrategy", "IntermediateStrategy", "NoviceStrategy"]

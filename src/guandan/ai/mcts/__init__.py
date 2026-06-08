"""MCTS (Monte Carlo Tree Search) 模块。

M3 实现 IS-MCTS（Information Set Monte Carlo Tree Search）用于档 3 职业级 AI。

核心组件：
- node.py: MCTSNode 数据结构
- determinize.py: 信息集确定化（隐藏信息推断）
- search.py: MCTS 主循环（Selection/Expansion/Simulation/Backpropagation）

算法概述：
1. Determinization: 根据已出牌，随机生成其他玩家的可能手牌
2. MCTS: 在确定化的世界中运行树搜索
3. Selection: UCB1 选择最优节点
4. Expansion: 扩展新子节点
5. Simulation: 快速玩到游戏结束（rollout）
6. Backpropagation: 回传结果更新胜率

参数配置：
- iterations: MCTS 迭代次数（默认 200）
- ucb_c: UCB1 探索常数（默认 1.41）
- max_depth: 最大搜索深度（默认 10）
- rollout_strategy: Simulation 策略档位（默认 1）
"""
from __future__ import annotations

from .determinize import determinize
from .node import MCTSNode
from .search import mcts_search

__all__ = [
    "MCTS_CONFIG",
    "MCTSNode",
    "determinize",
    "mcts_search",
]

# 默认配置
MCTS_CONFIG = {
    "iterations": 100,  # 降低迭代次数以提升速度（从 200 降到 100）
    "ucb_c": 1.41,
    "max_depth": 10,
    "rollout_strategy": 1,
    "top_actions": 5,
}

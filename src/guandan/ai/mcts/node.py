"""MCTSNode：蒙特卡洛树搜索的节点数据结构。

每个节点代表游戏的一个状态，包含：
- 状态信息（GameState）
- 统计信息（访问次数、累计胜利值）
- 树结构（父节点、子节点）
- 未尝试的动作列表
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ...engine.hand import Pattern
from ...engine.state import GameState


@dataclass
class MCTSNode:
    """MCTS 树节点。"""

    state: GameState  # 当前游戏状态
    player: int  # 当前轮到的玩家（0-3）
    parent: Optional[MCTSNode] = None
    action: Optional[Pattern] = None  # 从父节点到此节点的动作（None = pass）
    children: list[MCTSNode] = field(default_factory=list)
    visits: int = 0  # 访问次数
    wins: float = 0.0  # 累计胜利值（从 root 玩家视角）
    untried_actions: list[Optional[Pattern]] = field(default_factory=list)

    def is_terminal(self) -> bool:
        """判断是否为终局节点。"""
        return self.state.finished

    def is_fully_expanded(self) -> bool:
        """判断是否已展开所有子节点。"""
        return len(self.untried_actions) == 0

    def win_rate(self) -> float:
        """计算胜率（用于 UCB1）。"""
        if self.visits == 0:
            return 0.0
        return self.wins / self.visits

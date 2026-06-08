"""档 3 职业策略：IS-MCTS (Information Set Monte Carlo Tree Search)。

职业级 AI 使用 MCTS 算法进行决策：
1. 确定化：根据已知信息推断其他玩家可能的手牌
2. MCTS 搜索：在确定化的世界中运行树搜索
3. 返回最佳行动

相比档 0/1/2 的启发式策略，MCTS 能够前瞻多步，做出更优决策。
"""
from __future__ import annotations

import random
from typing import Optional

from ...engine.hand import Pattern
from ...engine.state import GameState
from ..mcts import MCTS_CONFIG
from ..mcts.determinize import determinize
from ..mcts.node import MCTSNode
from ..mcts.search import mcts_search
from ..valuation import enumerate_candidate_plays
from .advanced import AdvancedStrategy


class ProfessionalStrategy:
    """职业 AI：IS-MCTS 搜索。"""

    name = "职业"
    difficulty = 3

    def __init__(
        self,
        iterations: int = 200,
        ucb_c: float = MCTS_CONFIG["ucb_c"],
        max_actions: int = 5,
        rollout_strategy: int = 1,
        rng: Optional[random.Random] = None,
        mcts_hand_threshold: int = 10,
        rollout_max_turns: int = 80,
    ):
        """初始化职业策略。

        Args:
            iterations: MCTS 迭代次数（默认 200）
            ucb_c: UCB1 探索常数（默认 1.41）
            max_actions: 每个节点考虑的最大候选动作数（默认 5）
            rollout_strategy: rollout 策略档位（默认 1）
            rng: 随机数生成器（测试时可 seed）
            mcts_hand_threshold: 手牌数不大于该值时启用 MCTS，前中期用快速策略
            rollout_max_turns: 单次 MCTS rollout 最多模拟多少手
        """
        self.iterations = iterations
        self.ucb_c = ucb_c
        self.max_actions = max_actions
        self.rollout_strategy = rollout_strategy
        self.rng = rng if rng is not None else random.Random()
        self.mcts_hand_threshold = mcts_hand_threshold
        self.rollout_max_turns = rollout_max_turns
        self._fast_strategy = AdvancedStrategy()

    def select_pattern(
        self, state: GameState, player: int
    ) -> Optional[Pattern]:
        """用 IS-MCTS 选择最佳出牌。

        流程：
        1. 确定化：生成其他玩家可能的手牌分配
        2. MCTS 搜索：在确定化的世界中运行树搜索
        3. 返回最佳行动（访问次数最多的子节点）

        Args:
            state: 当前游戏状态
            player: 当前玩家

        Returns:
            最佳牌型（None 表示过牌）
        """
        finish = self._finish_now(state, player)
        if finish is not None:
            return finish

        if not self._should_use_mcts(state, player):
            return self._fast_strategy.select_pattern(state, player)

        # 1. 确定化：生成其他玩家的可能手牌
        determinized_state = determinize(state, player, self.rng)

        # 2. 创建 MCTS 根节点
        root = MCTSNode(
            state=determinized_state,
            player=player,
        )

        # 3. MCTS 搜索
        best_child = mcts_search(
            root=root,
            iterations=self.iterations,
            ucb_c=self.ucb_c,
            max_actions=self.max_actions,
            rollout_strategy=self.rollout_strategy,
            rollout_max_turns=self.rollout_max_turns,
        )

        # 4. 返回最佳行动
        if best_child is None:
            return None

        return best_child.action

    def _finish_now(self, state: GameState, player: int) -> Optional[Pattern]:
        """如果有合法牌型能一次出完当前手牌，直接返回。"""
        hand_size = state.hand_size(player)
        if hand_size == 0:
            return None
        for candidate in enumerate_candidate_plays(
            state, player, max_candidates=max(self.max_actions, 8)
        ):
            if len(candidate.cards) == hand_size:
                return candidate
        return None

    def _should_use_mcts(self, state: GameState, player: int) -> bool:
        """M6 性能闸门：只在中后期或关键局面启用 MCTS。"""
        if state.hand_size(player) <= self.mcts_hand_threshold:
            return True
        opponent_min = min(
            (state.hand_size(p) for p in range(4) if p != player and state.hand_size(p) > 0),
            default=0,
        )
        return 0 < opponent_min <= self.mcts_hand_threshold

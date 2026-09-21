"""档 3 职业策略：团队感知的配对根动作评估。

每轮从根玩家的信息集重新采样隐藏牌，并让候选动作共享该隐藏世界。生产默认
把预算均匀分给根动作；旧 SO-ISMCTS 保留为可切换的对照路径。
"""
from __future__ import annotations

import random
from typing import Optional

from ...engine.hand import Pattern
from ...engine.state import GameState
from ..context import opponent_min_cards
from ..endgame import legal_finish_pattern
from ..mcts import MCTS_CONFIG
from ..mcts.information_set import (
    SearchResult,
    SearchStyle,
)
from ..mcts.information_set import information_set_search as mcts_search
from ..mcts.root_search import root_action_search
from .advanced import AdvancedStrategy

DEFAULT_ITERATIONS = int(MCTS_CONFIG["iterations"])
DEFAULT_UCB_C = float(MCTS_CONFIG["ucb_c"])
DEFAULT_MAX_ACTIONS = int(MCTS_CONFIG["top_actions"])
DEFAULT_ROLLOUT_STRATEGY = int(MCTS_CONFIG["rollout_strategy"])
DEFAULT_HAND_THRESHOLD = int(MCTS_CONFIG["hand_threshold"])
DEFAULT_ROLLOUT_MAX_TURNS = int(MCTS_CONFIG["rollout_max_turns"])
DEFAULT_TIME_BUDGET_MS = int(MCTS_CONFIG["time_budget_ms"])
DEFAULT_MAX_DEPTH = int(MCTS_CONFIG["max_depth"])
DEFAULT_PRIOR_WEIGHT = float(MCTS_CONFIG["prior_weight"])
DEFAULT_WIDENING_C = float(MCTS_CONFIG["widening_c"])
DEFAULT_WIDENING_ALPHA = float(MCTS_CONFIG["widening_alpha"])
DEFAULT_SEARCH_MODE = str(MCTS_CONFIG["search_mode"])


class ProfessionalStrategy:
    """职业 AI：配对隐藏世界上的根动作价值比较。"""

    name = "职业"
    difficulty = 3
    uses_stochastic_pass = False

    def __init__(
        self,
        iterations: int = DEFAULT_ITERATIONS,
        ucb_c: float = DEFAULT_UCB_C,
        max_actions: int = DEFAULT_MAX_ACTIONS,
        rollout_strategy: int = DEFAULT_ROLLOUT_STRATEGY,
        rng: Optional[random.Random] = None,
        mcts_hand_threshold: int = DEFAULT_HAND_THRESHOLD,
        rollout_max_turns: int = DEFAULT_ROLLOUT_MAX_TURNS,
        time_budget_ms: int = DEFAULT_TIME_BUDGET_MS,
        max_tree_depth: int = DEFAULT_MAX_DEPTH,
        prior_weight: float = DEFAULT_PRIOR_WEIGHT,
        widening_c: float = DEFAULT_WIDENING_C,
        widening_alpha: float = DEFAULT_WIDENING_ALPHA,
        search_mode: str = DEFAULT_SEARCH_MODE,
    ):
        """初始化职业策略。

        Args:
            iterations: 单次决策的最大根动作评估次数（默认 32）
            ucb_c: 信息集树探索常数（默认 1.20）
            max_actions: 根节点考虑的搜索候选上限（默认 6，另含过牌/greedy）
            rollout_strategy: rollout 策略档位（默认 1）
            rng: 随机数生成器（测试时可 seed）
            mcts_hand_threshold: 手牌数不大于该值时启用搜索，前中期用快速策略
            rollout_max_turns: 单次 rollout 最多模拟多少手
            time_budget_ms: 单次决策时钟预算（默认 240ms，0 表示禁用）
            max_tree_depth: 单次模拟的最大树深度（默认 12）
            prior_weight: 动作先验在选择公式中的权重
            widening_c: 渐进扩展的规模系数
            widening_alpha: 渐进扩展的访问次数指数
            search_mode: ``root`` 使用配对根动作评估；``tree`` 使用旧 SO-ISMCTS
        """
        self.iterations = iterations
        self.ucb_c = ucb_c
        self.max_actions = max_actions
        self.rollout_strategy = rollout_strategy
        self.rng = rng if rng is not None else random.Random()
        self.mcts_hand_threshold = mcts_hand_threshold
        self.rollout_max_turns = rollout_max_turns
        self.time_budget_ms = time_budget_ms
        self.max_tree_depth = max_tree_depth
        self.prior_weight = prior_weight
        self.widening_c = widening_c
        self.widening_alpha = widening_alpha
        if search_mode not in {"root", "tree"}:
            raise ValueError("search_mode must be 'root' or 'tree'")
        self.search_mode = search_mode
        self.last_search: SearchResult | None = None
        self._fast_strategy = AdvancedStrategy()

    def select_pattern(
        self, state: GameState, player: int
    ) -> Optional[Pattern]:
        """用配对根动作评估（或显式指定的旧树搜索）选择出牌。

        流程：
        1. 每轮采样一个与公开信息一致的隐藏世界
        2. 所有根动作共享该世界，分别 rollout 并累计团队价值
        3. 返回平均价值最高的动作

        Args:
            state: 当前游戏状态
            player: 当前玩家

        Returns:
            最佳牌型（None 表示过牌）
        """
        self.last_search = None
        finish = self._finish_now(state, player)
        if finish is not None:
            return finish

        if not self._should_use_mcts(state, player):
            return self._fast_strategy.select_pattern(state, player)

        if self.search_mode == "root":
            result = root_action_search(
                state,
                player,
                rng=self.rng,
                iterations=self.iterations,
                time_budget_ms=self.time_budget_ms,
                max_actions=self.max_actions,
                rollout_strategy=self.rollout_strategy,
                rollout_max_turns=self.rollout_max_turns,
                prior_weight=self.prior_weight,
                style=self._search_style(),
                adaptive=False,
            )
        else:
            result = mcts_search(
                state,
                player,
                rng=self.rng,
                iterations=self.iterations,
                time_budget_ms=self.time_budget_ms,
                max_actions=self.max_actions,
                max_tree_depth=self.max_tree_depth,
                rollout_strategy=self.rollout_strategy,
                rollout_max_turns=self.rollout_max_turns,
                exploration=self.ucb_c,
                prior_weight=self.prior_weight,
                widening_c=self.widening_c,
                widening_alpha=self.widening_alpha,
                style=self._search_style(),
            )
        if result is None:  # Test doubles and defensive compatibility.
            return None
        self.last_search = result
        return result.pattern

    def _search_style(self) -> SearchStyle:
        return SearchStyle()

    def _finish_now(self, state: GameState, player: int) -> Optional[Pattern]:
        """如果有合法牌型能一次出完当前手牌，直接返回。"""
        return legal_finish_pattern(state, player)

    def _should_use_mcts(self, state: GameState, player: int) -> bool:
        """M6 性能闸门：只在中后期或关键局面启用搜索。"""
        if state.hand_size(player) <= self.mcts_hand_threshold:
            return True
        opponent_min = opponent_min_cards(state, player)
        return 0 < opponent_min <= self.mcts_hand_threshold

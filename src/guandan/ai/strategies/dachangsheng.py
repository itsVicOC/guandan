"""档 4 戴长胜策略：更高预算的团队感知 SO-ISMCTS。

戴长胜风格特点：
- 炸弹审慎：综合紧迫度、终局价值与控场收益决定使用时机
- 控场节奏：掌握出牌节奏，控制局势
- 配合意识：与队友高度配合

实现方式：
- 继承 ProfessionalStrategy 的团队对抗搜索
- 加载经自对弈筛选的 profile 参数
- 把风格参数作为搜索先验，不在搜索结束后否决首选动作
"""
from __future__ import annotations

import random
from typing import Mapping, Optional

from ...engine.hand import Pattern
from ...engine.state import GameState
from ..mcts.information_set import SearchStyle
from ..profiles import load_profile
from .professional import ProfessionalStrategy


class DaiChangshengStrategy(ProfessionalStrategy):
    """戴长胜风格 AI：高预算 SO-ISMCTS 与自对弈风格先验。"""

    name = "戴长胜"
    difficulty = 4

    def __init__(
        self,
        profile_name: str = "dachangsheng",
        rng: Optional[random.Random] = None,
        style_overrides: Mapping[str, float] | None = None,
        mcts_overrides: Mapping[str, int | float] | None = None,
    ):
        """初始化戴长胜策略。

        Args:
            profile_name: Profile 文件名（默认 "dachangsheng"）
            rng: 随机数生成器（测试时可 seed）
        """
        # 加载 profile
        self.profile = load_profile(profile_name)
        self.style = dict(self.profile["style"])
        if style_overrides:
            self.style.update(style_overrides)
        self.pass_probability_multiplier = self.style.get("pass_probability_multiplier", 1.0)

        # 初始化 MCTS（用 profile 的参数）
        mcts_config = dict(self.profile["mcts"])
        if mcts_overrides:
            mcts_config.update(mcts_overrides)
        super().__init__(
            iterations=mcts_config.get("iterations", 96),
            ucb_c=mcts_config.get("ucb_c", 1.15),
            max_actions=mcts_config.get("top_actions", 12),
            rollout_strategy=mcts_config.get("rollout_strategy", 2),
            rng=rng,
            mcts_hand_threshold=mcts_config.get("hand_threshold", 10),
            rollout_max_turns=mcts_config.get("rollout_max_turns", 48),
            time_budget_ms=mcts_config.get("time_budget_ms", 420),
            max_tree_depth=mcts_config.get("max_depth", 14),
            prior_weight=mcts_config.get("prior_weight", 0.22),
            widening_c=mcts_config.get("widening_c", 2.0),
            widening_alpha=mcts_config.get("widening_alpha", 0.5),
        )

    def select_pattern(
        self, state: GameState, player: int
    ) -> Optional[Pattern]:
        """用高预算 SO-ISMCTS 和风格先验选择最佳出牌。

        流程：
        1. 把 profile 参数转换为动作搜索先验
        2. 调用父类的团队对抗搜索并直接采用搜索结果

        Args:
            state: 当前游戏状态
            player: 当前玩家

        Returns:
            最佳牌型（None 表示过牌）
        """
        return super().select_pattern(state, player)

    def _search_style(self) -> SearchStyle:
        """Translate mutable profile values into search priors."""
        return SearchStyle(
            # A style prior should rank alternatives, not recreate the former
            # hard veto.  Even the most bomb-conservative profile retains at
            # least a meaningful fraction of the neutral prior.
            bomb_willingness=max(
                0.25,
                1.25 - float(self.style["bomb_threshold"]),
            ),
            teammate_awareness=float(self.style["teammate_awareness"]),
            control_priority=float(self.style["control_priority"]),
        )

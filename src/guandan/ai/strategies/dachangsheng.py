"""档 4 戴长胜策略：更高预算的团队感知根动作评估。

自对弈选中的风格先验是中性值；此档扩大候选和采样，
并在极短残局尝试限时团队搜索。风格参数只在根动作排序中作弱修正。
"""
from __future__ import annotations

import random
import time
from typing import Mapping, Optional, cast

from ...engine.hand import Pattern
from ...engine.state import GameState
from ..mcts.endgame_solver import UNSOLVED, solve_endgame
from ..mcts.information_set import ActionStatistics, SearchStyle
from ..profiles import load_profile
from .professional import ProfessionalStrategy


class DaiChangshengStrategy(ProfessionalStrategy):
    """戴长胜风格 AI：高预算根评估、残局搜索与风格先验。"""

    name = "戴长胜"
    difficulty = 4

    def __init__(
        self,
        profile_name: str = "dachangsheng",
        rng: Optional[random.Random] = None,
        style_overrides: Mapping[str, float] | None = None,
        mcts_overrides: Mapping[str, int | float | str] | None = None,
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
        # 初始化搜索（用 profile 的参数）
        mcts_config = dict(self.profile["mcts"])
        if mcts_overrides:
            mcts_config.update(mcts_overrides)
        critical_budget = (
            0 if mcts_config.get("time_budget_ms") == 0
            else mcts_config.get("critical_time_budget_ms", 5000)
        )
        super().__init__(
            iterations=mcts_config.get("iterations", 768),
            ucb_c=mcts_config.get("ucb_c", 1.15),
            max_actions=mcts_config.get("top_actions", 10),
            rollout_strategy=mcts_config.get("rollout_strategy", 1),
            rng=rng,
            mcts_hand_threshold=mcts_config.get("hand_threshold", 27),
            rollout_max_turns=mcts_config.get("rollout_max_turns", 48),
            time_budget_ms=mcts_config.get("time_budget_ms", 2000),
            critical_time_budget_ms=critical_budget,
            max_tree_depth=mcts_config.get("max_depth", 14),
            prior_weight=mcts_config.get("prior_weight", 0.22),
            widening_c=mcts_config.get("widening_c", 2.0),
            widening_alpha=mcts_config.get("widening_alpha", 0.5),
            search_mode=str(mcts_config.get("search_mode", "root")),
        )
        self.reference_iterations = int(mcts_config.get(
            "reference_iterations",
            0,
        ))
        self.confidence_guard = bool(mcts_config.get("confidence_guard", False))

    def select_pattern(
        self, state: GameState, player: int
    ) -> Optional[Pattern]:
        """用高预算配对根评估和风格先验选择最佳出牌。

        流程：
        1. 把 profile 参数转换为动作搜索先验
        2. 调用父类的配对根动作评估并直接采用结果

        Args:
            state: 当前游戏状态
            player: 当前玩家

        Returns:
            最佳牌型（None 表示过牌）
        """
        if self._forced_pass(state, player):
            self.last_search = None
            return None
        total_remaining = sum(state.hand_size(seat) for seat in range(4))
        if total_remaining <= 12:
            started = time.perf_counter()
            full_budget_ms = self.critical_time_budget_ms
            deadline = (
                started + full_budget_ms * 0.7 / 1000.0
                if self.time_budget_ms > 0 else float("inf")
            )
            action = solve_endgame(
                state,
                player,
                rng=self.rng,
                deadline=deadline,
                max_actions=self.max_actions,
            )
            if action is not UNSOLVED:
                self.last_search = None
                return cast(Optional[Pattern], action)
            if self.time_budget_ms == 0:
                # Fixed-work evaluation still exercises the endgame feature;
                # solve_endgame's node ceiling provides its deterministic bound.
                return super().select_pattern(state, player)
            remaining_ms = max(0, full_budget_ms - int((time.perf_counter() - started) * 1000))
            if remaining_ms < 100:
                return self._fast_strategy.select_pattern(state, player)
            previous = self.critical_time_budget_ms
            self.critical_time_budget_ms = remaining_ms
            try:
                return super().select_pattern(state, player)
            finally:
                self.critical_time_budget_ms = previous
        return super().select_pattern(state, player)

    def _reference_action(self, state: GameState, player: int) -> Optional[Pattern]:
        """Use the tactical reference; retain nested search as a research override."""
        if self.reference_iterations == 0:
            return super()._reference_action(state, player)
        budget = (
            self.critical_time_budget_ms
            if self._critical_decision(state, player) else self.time_budget_ms
        )
        reference_budget = max(1, budget // 2) if budget > 0 else 0
        reference = ProfessionalStrategy(
            rng=random.Random(self.rng.getrandbits(64)),
            iterations=self.reference_iterations,
            time_budget_ms=reference_budget,
            critical_time_budget_ms=reference_budget,
        )
        return reference.select_pattern(state, player)

    def _minimum_search_gain(
        self, chosen: ActionStatistics | None, reference: ActionStatistics | None
    ) -> float:
        if (
            self.confidence_guard
            and chosen is not None
            and reference is not None
            and chosen.reference_key == reference.action_key
            and chosen.paired_standard_error is not None
        ):
            # Differences are paired by hidden world. A practical gain floor
            # avoids chasing tiny changes even when estimated variance is zero.
            return max(0.04, 1.64 * chosen.paired_standard_error)
        return super()._minimum_search_gain(chosen, reference)

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

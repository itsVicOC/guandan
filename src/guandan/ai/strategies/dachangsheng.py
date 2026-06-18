"""档 4 戴长胜策略：IS-MCTS + 风格化参数。

戴长胜风格特点：
- 炸弹吝啬：不轻易出炸弹，保留控场能力
- 控场节奏：掌握出牌节奏，控制局势
- 配合意识：与队友高度配合

实现方式：
- 继承 ProfessionalStrategy（IS-MCTS）
- 加载 profile 配置风格参数
- 在决策中应用风格化规则
"""
from __future__ import annotations

import random
from typing import Optional

from ...engine.hand import Pattern, PatternType
from ...engine.state import GameState, is_teammate, partner_of
from ...engine.trick import current_top_player
from ..context import opponent_min_cards
from ..profiles import load_profile
from .professional import ProfessionalStrategy


class DaiChangshengStrategy(ProfessionalStrategy):
    """戴长胜风格 AI：IS-MCTS + 风格化参数。"""

    name = "戴长胜"
    difficulty = 4

    def __init__(
        self,
        profile_name: str = "dachangsheng",
        rng: Optional[random.Random] = None,
    ):
        """初始化戴长胜策略。

        Args:
            profile_name: Profile 文件名（默认 "dachangsheng"）
            rng: 随机数生成器（测试时可 seed）
        """
        # 加载 profile
        self.profile = load_profile(profile_name)
        self.style = self.profile["style"]
        self.pass_probability_multiplier = self.style.get("pass_probability_multiplier", 1.0)

        # 初始化 MCTS（用 profile 的参数）
        mcts_config = self.profile["mcts"]
        super().__init__(
            iterations=mcts_config.get("iterations", 150),
            ucb_c=mcts_config.get("ucb_c", 1.41),
            max_actions=mcts_config.get("top_actions", 5),
            rollout_strategy=mcts_config.get("rollout_strategy", 2),
            rng=rng,
            mcts_hand_threshold=mcts_config.get("hand_threshold", 10),
            rollout_max_turns=mcts_config.get("rollout_max_turns", 80),
        )

    def select_pattern(
        self, state: GameState, player: int
    ) -> Optional[Pattern]:
        """用 IS-MCTS + 风格化选择最佳出牌。

        流程：
        1. 调用父类 MCTS 搜索
        2. 应用风格化规则调整决策

        Args:
            state: 当前游戏状态
            player: 当前玩家

        Returns:
            最佳牌型（None 表示过牌）
        """
        # 1. MCTS 搜索
        pattern = super().select_pattern(state, player)

        # 2. 应用风格化规则
        return self._apply_style(state, player, pattern)

    def _apply_style(
        self, state: GameState, player: int, pattern: Optional[Pattern]
    ) -> Optional[Pattern]:
        """应用戴长胜风格化规则。

        Args:
            state: 当前游戏状态
            player: 当前玩家
            pattern: MCTS 选择的牌型

        Returns:
            调整后的牌型
        """
        if pattern is None:
            return None

        if len(pattern.cards) == state.hand_size(player):
            return pattern

        # 风格 1：炸弹吝啬
        if self._is_bomb(pattern):
            return pattern if self._should_use_bomb(state, player, pattern) else None

        # 风格 2：配合意识（队友协作）
        if (
            self._should_let_teammate_play(state, player)
            and self.rng.random() < self.style["teammate_awareness"]
        ):
            return None

        return pattern

    def _is_bomb(self, pattern: Pattern) -> bool:
        """判断是否为炸弹。"""
        return pattern.type in (
            PatternType.BOMB,
            PatternType.STRAIGHT_FLUSH,
            PatternType.FOUR_JOKERS,
        )

    def _should_use_bomb(
        self, state: GameState, player: int, bomb_pattern: Pattern
    ) -> bool:
        """判断是否应该使用炸弹（炸弹吝啬策略）。

        Args:
            state: 当前状态
            player: 当前玩家
            bomb_pattern: 炸弹牌型

        Returns:
            True 表示应该用炸弹，False 表示保留
        """
        # 能直接出完时，终局收益高于炸弹保留价值。
        if len(bomb_pattern.cards) == state.hand_size(player):
            return True

        # 如果队友已经头游，无需再出炸弹
        if self._teammate_is_first(state, player):
            return False

        # 如果对手即将获胜（手牌<=3），必须用炸弹阻止
        opponent_min_cards = self._get_opponent_min_cards(state, player)
        if opponent_min_cards <= 3 and opponent_min_cards > 0:
            return True

        # 根据 bomb_threshold 决定
        # 计算"紧迫度"：对手最少手牌数的倒数
        urgency = 1.0 / opponent_min_cards if opponent_min_cards > 0 else 0.0

        # threshold 越高，越不愿意用炸弹
        return urgency > self.style["bomb_threshold"]

    def _should_let_teammate_play(self, state: GameState, player: int) -> bool:
        """判断是否应该让队友出牌（配合意识）。

        Args:
            state: 当前状态
            player: 当前玩家

        Returns:
            True 表示应该让队友走
        """
        partner = partner_of(player)

        # 队友已出完，无需让
        if state.hand_size(partner) == 0:
            return False

        # 对手报单时优先护航，不用风格化让牌覆盖拦截。
        if self._get_opponent_min_cards(state, player) == 1:
            return False

        # 队友手牌少且正在领先（是当前出牌者），让队友收这一轮
        return (
            state.hand_size(partner) <= 5
            and bool(state.table)
            and self._partner_is_leading(state, player)
        )

    def _teammate_is_first(self, state: GameState, player: int) -> bool:
        """判断队友是否已经头游。"""
        if not state.finish_order:
            return False
        first_player = state.finish_order[0]
        return is_teammate(first_player, player)

    def _get_opponent_min_cards(self, state: GameState, player: int) -> int:
        """获取对手最少手牌数。"""
        return opponent_min_cards(state, player)

    def _partner_is_leading(self, state: GameState, player: int) -> bool:
        """判断队友是否正在控场（是桌面上最后一个出牌的玩家）。"""
        if not state.table:
            return False
        top_player = current_top_player(state)
        return top_player is not None and is_teammate(top_player, player)

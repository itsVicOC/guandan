"""档 3 职业策略：全局面团队感知配对根动作评估。"""
from __future__ import annotations

import random
import time
from typing import Any, Optional

from ...engine.hand import Pattern
from ...engine.rules.comparator import is_bomb_type
from ...engine.state import GameState
from ..candidates import enumerate_legal_patterns, pattern_key
from ..config import DecisionBudget, ResearchConfig, SearchConfig, config_field
from ..context import opponent_min_cards
from ..endgame import legal_finish_pattern
from ..match_value import round_value_span
from ..mcts import MCTS_CONFIG
from ..mcts.information_set import (
    PASS_ACTION,
    ActionStatistics,
    SearchResult,
    SearchStyle,
)
from ..mcts.information_set import information_set_search as mcts_search
from ..mcts.root_search import root_action_candidates, root_action_search
from ..tactics import select_heuristic_action
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
DEFAULT_CRITICAL_TIME_BUDGET_MS = 2000
DEFAULT_PARTNER_ADAPTATION = bool(MCTS_CONFIG.get("partner_adaptation", False))
DEFAULT_RESPONSE_CHAIN = bool(MCTS_CONFIG.get("response_chain", False))
DEFAULT_ACTION_RANKER = bool(MCTS_CONFIG.get("action_ranker", False))
DEFAULT_URGENT_BLOCKING = bool(MCTS_CONFIG.get("urgent_blocking", False))
DEFAULT_URGENT_BLOCKING_WEIGHT = float(MCTS_CONFIG.get("urgent_blocking_weight", 12.0))


class ProfessionalStrategy:
    """职业 AI：配对隐藏世界上的根动作价值比较。"""

    name = "职业"
    difficulty = 3
    uses_stochastic_pass = False

    iterations = config_field("search_config", "iterations")
    ucb_c = config_field("search_config", "ucb_c")
    max_actions = config_field("search_config", "max_actions")
    rollout_strategy = config_field("search_config", "rollout_strategy")
    mcts_hand_threshold = config_field("search_config", "mcts_hand_threshold")
    rollout_max_turns = config_field("search_config", "rollout_max_turns")
    time_budget_ms = config_field("search_config", "time_budget_ms")
    critical_time_budget_ms = config_field("search_config", "critical_time_budget_ms")
    max_tree_depth = config_field("search_config", "max_tree_depth")
    prior_weight = config_field("search_config", "prior_weight")
    widening_c = config_field("search_config", "widening_c")
    widening_alpha = config_field("search_config", "widening_alpha")
    search_mode = config_field("search_config", "search_mode")
    team_tactics = config_field("research_config", "team_tactics")
    lead_chain = config_field("research_config", "lead_chain")
    heterogeneous_rollouts = config_field("research_config", "heterogeneous_rollouts")
    partner_bomb_guard = config_field("research_config", "partner_bomb_guard")
    partner_adaptation = config_field("research_config", "partner_adaptation")
    response_chain = config_field("research_config", "response_chain")
    action_ranker = config_field("research_config", "action_ranker")
    reference_rollout_turns = config_field("research_config", "reference_rollout_turns")
    reference_refinement = config_field("research_config", "reference_refinement")
    urgent_blocking = config_field("research_config", "urgent_blocking")
    urgent_blocking_weight = config_field("research_config", "urgent_blocking_weight")

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
        critical_time_budget_ms: int | None = None,
        team_tactics: bool = False,
        lead_chain: bool = False,
        heterogeneous_rollouts: bool = False,
        partner_bomb_guard: bool = False,
        partner_adaptation: bool = DEFAULT_PARTNER_ADAPTATION,
        response_chain: bool = DEFAULT_RESPONSE_CHAIN,
        action_ranker: bool = DEFAULT_ACTION_RANKER,
        reference_rollout_turns: int = 0,
        reference_refinement: bool = False,
        urgent_blocking: bool = DEFAULT_URGENT_BLOCKING,
        urgent_blocking_weight: float = DEFAULT_URGENT_BLOCKING_WEIGHT,
        *,
        search_config: SearchConfig | None = None,
        research_config: ResearchConfig | None = None,
    ):
        """初始化职业策略。

        Args:
            iterations: 单次决策的最大根动作评估次数（默认 256）
            ucb_c: 信息集树探索常数（默认 1.20）
            max_actions: 根节点考虑的搜索候选上限（默认 6，另含过牌/greedy）
            rollout_strategy: rollout 策略档位（默认 1）
            rng: 随机数生成器（测试时可 seed）
            mcts_hand_threshold: 研究用闸门；默认 27 表示全局面搜索
            rollout_max_turns: 单次 rollout 最多模拟多少手
            time_budget_ms: 常规决策时钟预算（默认 1000ms，0 表示禁用）
            max_tree_depth: 单次模拟的最大树深度（默认 12）
            prior_weight: 动作先验在选择公式中的权重
            widening_c: 渐进扩展的规模系数
            widening_alpha: 渐进扩展的访问次数指数
            search_mode: ``root`` 使用配对根动作评估；``tree`` 使用旧 SO-ISMCTS
        """
        self.search_config = search_config or SearchConfig(
            iterations=iterations, ucb_c=ucb_c, max_actions=max_actions,
            rollout_strategy=rollout_strategy, mcts_hand_threshold=mcts_hand_threshold,
            rollout_max_turns=rollout_max_turns, time_budget_ms=time_budget_ms,
            critical_time_budget_ms=(critical_time_budget_ms if critical_time_budget_ms is not None
                                     else 0 if time_budget_ms == 0 else DEFAULT_CRITICAL_TIME_BUDGET_MS),
            max_tree_depth=max_tree_depth, prior_weight=prior_weight, widening_c=widening_c,
            widening_alpha=widening_alpha, search_mode=search_mode,
        )
        self.research_config = research_config or ResearchConfig(
            team_tactics=team_tactics, lead_chain=lead_chain, heterogeneous_rollouts=heterogeneous_rollouts,
            partner_bomb_guard=partner_bomb_guard, partner_adaptation=partner_adaptation,
            response_chain=response_chain, action_ranker=action_ranker,
            reference_rollout_turns=reference_rollout_turns, reference_refinement=reference_refinement,
            urgent_blocking=urgent_blocking, urgent_blocking_weight=urgent_blocking_weight,
        )
        self.research_config.validate(self.search_config)
        if self.team_tactics:
            self.rollout_strategy = max(3, self.rollout_strategy)
        self.rng = rng if rng is not None else random.Random()
        self.last_search: SearchResult | None = None
        self.last_decision_reason = "not_started"
        self.last_urgent_blocking: dict | None = None
        self._urgent_candidates: list[Pattern | None] | None = None
        self.last_guard: dict | None = None
        self._tactical_deadline: float | None = None
        self._inherited_budget: DecisionBudget | None = None
        self._decision_budget: DecisionBudget | None = None
        self._fast_strategy = AdvancedStrategy(team_tactics=self.team_tactics, lead_chain=self.lead_chain, partner_bomb_guard=self.partner_bomb_guard)

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
        self.last_guard = None
        self.last_urgent_blocking = None
        self._urgent_candidates = None
        self.last_decision_reason = "search"
        if self._forced_pass(state, player):
            self.last_decision_reason = "forced_pass"
            return None
        if not self._should_use_mcts(state, player):
            self.last_decision_reason = "threshold_fallback"
            return self._fast_strategy.select_pattern(state, player)

        decision_started = time.perf_counter()
        budget = (
            self.critical_time_budget_ms
            if self._critical_decision(state, player) else self.time_budget_ms
        )
        decision_budget = self._inherited_budget or DecisionBudget.start(budget, started=decision_started)
        self._decision_budget = decision_budget
        self._tactical_deadline = decision_budget.slice(0.10).deadline
        tactical = (
            self._reference_action(state, player)
            if self.search_mode == "root"
            else None
        )
        if self.last_urgent_blocking is not None:
            self.last_urgent_blocking["stage_elapsed_seconds"] = time.perf_counter() - decision_started
            self.last_urgent_blocking["stage_budget_ms"] = budget * 0.10 if budget > 0 else 0
        if decision_budget.deadline is not None:
            budget = max(1, decision_budget.remaining_ms())

        try:
            if self.search_mode == "root":
                root_options: dict[str, Any] = {"decision_budget": decision_budget}
                if self._urgent_candidates is not None:
                    root_options["_candidate_actions"] = self._urgent_candidates
                if self.partner_adaptation:
                    root_options["partner_adaptation"] = True
                if self.response_chain:
                    root_options.update(response_chain=True, chain_worlds=8 if self.difficulty == 4 else 4)
                if self.action_ranker:
                    root_options["action_ranker"] = True
                if self.reference_rollout_turns:
                    root_options["reference_rollout_turns"] = self.reference_rollout_turns
                if self.reference_refinement:
                    root_options["reference_refinement"] = True
                result = root_action_search(
                    state,
                    player,
                    rng=self.rng,
                    iterations=self.iterations,
                    time_budget_ms=budget,
                    max_actions=self.max_actions,
                    rollout_strategy=self.rollout_strategy,
                    rollout_max_turns=self.rollout_max_turns,
                    prior_weight=self.prior_weight,
                    style=self._search_style(),
                    adaptive=False,
                    reference_actions=(tactical,),
                    heterogeneous_rollouts=self.heterogeneous_rollouts,
                    **root_options,
                )
            else:
                result = mcts_search(
                    state,
                    player,
                    rng=self.rng,
                    iterations=self.iterations,
                    time_budget_ms=budget,
                    max_actions=self.max_actions,
                    max_tree_depth=self.max_tree_depth,
                    rollout_strategy=self.rollout_strategy,
                    rollout_max_turns=self.rollout_max_turns,
                    exploration=self.ucb_c,
                    prior_weight=self.prior_weight,
                    widening_c=self.widening_c,
                    widening_alpha=self.widening_alpha,
                    style=self._search_style(),
                    decision_budget=decision_budget,
                )
        except ValueError as exc:
            # Hand-constructed test/replay states may lack a complete public
            # deck accounting.  Keep the playable policy available there.
            if "belief sampler has no remaining hand capacity" not in str(exc):
                raise
            self.last_decision_reason = "incomplete_state_fallback"
            return self._fast_strategy.select_pattern(state, player)
        if result is None:  # Test doubles and defensive compatibility.
            return None
        self.last_search = result
        if not result.simulations and self.search_mode == "tree":
            self.last_decision_reason = "search_budget_fallback"
            return self._fast_strategy.select_pattern(state, player)
        if self.search_mode == "root":
            tactical_key = PASS_ACTION if tactical is None else pattern_key(tactical)
            chosen_key = PASS_ACTION if result.pattern is None else pattern_key(result.pattern)
            if chosen_key != tactical_key:
                stats = {entry.action_key: entry for entry in result.actions}
                chosen = stats.get(chosen_key)
                reference = stats.get(tactical_key)
                required_gain = self._gain_threshold(state, chosen, reference)
                urgency = opponent_min_cards(state, player)
                if tactical is None and urgency > 5:
                    required_gain = max(required_gain, 0.25 * round_value_span(state))
                    if (
                        result.pattern is not None
                        and is_bomb_type(result.pattern.type)
                        and state.hand_size(player) - len(result.pattern.cards) > 3
                    ):
                        required_gain = max(required_gain, 0.40 * round_value_span(state))
                self.last_guard = {
                    "required_gain": required_gain,
                    "observed_gain": chosen.mean_value - reference.mean_value if chosen and reference else None,
                    "payoff_span": round_value_span(state),
                    "common_samples": result.common_samples,
                    "paired_standard_error": chosen.paired_standard_error if chosen else None,
                }
                # Sparse, clock-truncated rollouts should not replace a sound
                # tactical move on a tiny, noisy lead.  Both actions were
                # evaluated on the same hidden worlds.
                if (
                    chosen is None
                    or reference is None
                    or min(entry.visits for entry in result.actions) < 6
                    or chosen.mean_value - reference.mean_value < required_gain
                ):
                    self.last_decision_reason = "tactical_guard"
                    return tactical
            else:
                self.last_decision_reason = "agrees_with_tactical"
        return result.pattern

    def _minimum_search_gain(
        self, chosen: ActionStatistics | None, reference: ActionStatistics | None
    ) -> float:
        return 0.14

    def _gain_threshold(self, state: GameState, chosen: ActionStatistics | None, reference: ActionStatistics | None) -> float:
        return self._minimum_search_gain(chosen, reference) * round_value_span(state)

    def _reference_action(self, state: GameState, player: int) -> Optional[Pattern]:
        """Lower-tier decision that additional search must demonstrably improve."""
        baseline = select_heuristic_action(state, player, 2, team_tactics=self.team_tactics,
                                       lead_chain=self.lead_chain, partner_bomb_guard=self.partner_bomb_guard, deadline=self._tactical_deadline)
        if not self.urgent_blocking:
            return baseline
        from ..candidates import smallest_legal_pattern
        from ..urgent_blocking import action_key, blocking_reference

        proposed, report = blocking_reference(
            state, player, baseline, weight=self.urgent_blocking_weight,
            deadline=self._tactical_deadline,
        )
        self.last_urgent_blocking = report
        if action_key(proposed) == action_key(baseline):
            return baseline
        patterns = root_action_candidates(state, player, max_actions=self.max_actions,
                                          reference_actions=(baseline,))
        if all(action_key(p) != action_key(proposed) for p in patterns):
            protected = {action_key(baseline), PASS_ACTION,
                         action_key(smallest_legal_pattern(state, player))}
            replace_at = next((i for i, candidate in reversed(list(enumerate(patterns)))
                               if candidate is not None
                               and action_key(candidate) not in protected
                               and len(candidate.cards) != state.hand_size(player)
                               and not is_bomb_type(candidate.type)), None)
            if replace_at is None:
                report.update(reason="no_replaceable_candidate", reference_key=action_key(baseline))
                return baseline
            patterns[replace_at] = proposed
            report["candidate_replaced"] = True
        if self._tactical_deadline is not None and time.perf_counter() >= self._tactical_deadline:
            report.update(reason="budget_limited", reference_key=action_key(baseline),
                          candidate_replaced=False, risks=[])
            return baseline
        self._urgent_candidates = patterns
        return proposed

    def _forced_pass(self, state: GameState, player: int) -> bool:
        """An empty response set has no decision to sample or search."""
        return (
            player == state.current_player()
            and bool(state.table)
            and not enumerate_legal_patterns(state, player)
        )

    def _search_style(self) -> SearchStyle:
        return SearchStyle()

    def _finish_now(self, state: GameState, player: int) -> Optional[Pattern]:
        """Check whether a legal one-play finish exists for urgency detection."""
        return legal_finish_pattern(state, player)

    def _should_use_mcts(self, state: GameState, player: int) -> bool:
        """Search throughout a normal game; retain the threshold override for tests."""
        if self.mcts_hand_threshold >= 27:
            return True
        if state.hand_size(player) <= self.mcts_hand_threshold:
            return True
        opponent_min = opponent_min_cards(state, player)
        return 0 < opponent_min <= self.mcts_hand_threshold

    def _critical_decision(self, state: GameState, player: int) -> bool:
        if any(0 < state.hand_size(seat) <= 10 for seat in range(4)):
            return True
        if state.table and is_bomb_type(state.table[-1].type):
            return True
        return self._finish_now(state, player) is not None

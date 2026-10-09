"""Typed production/research configuration and a shared absolute decision clock."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, fields, replace
from typing import Any, Mapping


@dataclass(frozen=True)
class SearchConfig:
    iterations: int = 256
    ucb_c: float = 1.2
    max_actions: int = 6
    rollout_strategy: int = 1
    mcts_hand_threshold: int = 27
    rollout_max_turns: int = 40
    time_budget_ms: int = 1000
    critical_time_budget_ms: int = -1
    max_tree_depth: int = 12
    prior_weight: float = 0.18
    widening_c: float = 1.8
    widening_alpha: float = 0.5
    search_mode: str = "root"

    def __post_init__(self) -> None:
        if self.critical_time_budget_ms == -1:
            object.__setattr__(self, "critical_time_budget_ms", 0 if self.time_budget_ms == 0 else 2000)
        if self.search_mode not in {"root", "tree"}:
            raise ValueError("search_mode must be 'root' or 'tree'")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> SearchConfig:
        aliases = {"max_actions": "top_actions", "mcts_hand_threshold": "hand_threshold",
                   "max_tree_depth": "max_depth"}
        defaults = cls(time_budget_ms=int(values.get("time_budget_ms", 1000)))
        data = {}
        for field in fields(cls):
            value = values.get(field.name, values.get(aliases.get(field.name, field.name), getattr(defaults, field.name)))
            data[field.name] = type(getattr(defaults, field.name))(value)
        return cls(**data)


@dataclass(frozen=True)
class ResearchConfig:
    team_tactics: bool = False
    lead_chain: bool = False
    heterogeneous_rollouts: bool = False
    partner_bomb_guard: bool = False
    partner_adaptation: bool = False
    response_chain: bool = False
    action_ranker: bool = False
    reference_rollout_turns: int = 0
    reference_refinement: bool = False
    urgent_blocking: bool = False
    urgent_blocking_weight: float = 12.0

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> ResearchConfig:
        defaults = cls()
        return cls(**{field.name: type(getattr(defaults, field.name))(
            values.get(field.name, getattr(defaults, field.name))) for field in fields(cls)})

    def validate(self, search: SearchConfig) -> None:
        if search.search_mode != "root" and (self.partner_adaptation or self.response_chain or self.action_ranker or self.reference_rollout_turns or self.reference_refinement or self.urgent_blocking):
            raise ValueError("partner adaptation, response chains and action ranking require root search")
        if not 0 <= self.reference_rollout_turns <= search.rollout_max_turns:
            raise ValueError("reference rollout turns must fit the rollout horizon")
        if self.reference_rollout_turns and (self.heterogeneous_rollouts or self.partner_adaptation):
            raise ValueError("reference rollouts cannot be combined with style adaptation")
        if self.reference_refinement and (self.team_tactics or self.lead_chain or self.partner_bomb_guard or search.rollout_strategy >= 3 or self.partner_adaptation or self.response_chain or self.action_ranker or self.reference_rollout_turns or self.heterogeneous_rollouts):
            raise ValueError("reference refinement requires an unmodified root search")
        if not math.isfinite(self.urgent_blocking_weight) or self.urgent_blocking_weight < 0:
            raise ValueError("urgent blocking weight must be finite and nonnegative")
        if self.urgent_blocking and (self.team_tactics or self.lead_chain or self.partner_bomb_guard or self.reference_refinement or self.response_chain or self.action_ranker):
            raise ValueError("urgent blocking requires the original tactical/root policy")


def config_field(group: str, name: str) -> property:
    """Legacy strategy attributes remain live views of immutable configuration."""
    def get(strategy: Any) -> Any:
        return getattr(getattr(strategy, group), name)

    def set_value(strategy: Any, value: Any) -> None:
        setattr(strategy, group, replace(getattr(strategy, group), **{name: value}))

    return property(get, set_value)


@dataclass(frozen=True)
class DecisionBudget:
    started: float
    deadline: float | None

    @classmethod
    def start(cls, milliseconds: int, *, started: float | None = None) -> DecisionBudget:
        now = time.perf_counter() if started is None else started
        return cls(now, now + milliseconds / 1000 if milliseconds > 0 else None)

    def remaining_ms(self) -> int:
        return max(0, int((self.deadline - time.perf_counter()) * 1000)) if self.deadline is not None else 0

    def slice(self, fraction: float) -> DecisionBudget:
        if not 0 <= fraction <= 1:
            raise ValueError("budget fraction must be in [0, 1]")
        now = time.perf_counter()
        return DecisionBudget(now, min(self.deadline, now + max(0, self.deadline - now) * fraction)
                              if self.deadline is not None else None)


def production_configuration(values: Mapping[str, Any]) -> dict[str, Any]:
    """Disabled research settings do not invalidate the production baseline."""
    toggles = {field.name for field in fields(ResearchConfig)} - {"urgent_blocking_weight"}
    toggles |= {"endgame_policy", "endgame_confidence", "reference_iterations"}
    result = {}
    for name, value in values.items():
        if isinstance(value, dict):
            result[name] = production_configuration(value)
        elif (name in toggles and not value) or (name == "urgent_blocking_weight" and not values.get("urgent_blocking")):
            continue
        else:
            result[name] = value
    return result

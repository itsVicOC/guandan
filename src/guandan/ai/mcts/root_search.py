"""Budget-efficient root action evaluation for imperfect-information play.

Unlike SO-ISMCTS, this search spends every rollout on comparing actions at the
current decision.  All actions in a sampling round share the same determinized
hidden world, which makes their value differences less noisy.  Adaptive mode
uses conservative successive halving after two and four samples per survivor.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from ...engine.hand import Pattern
from ...engine.state import GameState, clone_state_for_search
from ..candidates import observable_key, smallest_legal_pattern
from ..valuation import enumerate_search_candidates
from .determinize import determinize
from .information_set import (
    PASS_ACTION,
    ActionStatistics,
    SearchResult,
    SearchStyle,
    _action_prior,
    _apply_action,
)
from .search import simulate_state


@dataclass
class _RootArm:
    key: tuple
    pattern: Pattern | None
    prior: float
    values: list[float] = field(default_factory=list)

    @property
    def visits(self) -> int:
        return len(self.values)

    @property
    def mean_value(self) -> float:
        return sum(self.values) / len(self.values) if self.values else 0.5


def root_action_candidates(
    state: GameState,
    player: int,
    *,
    max_actions: int,
) -> list[Pattern | None]:
    """Return a deduplicated union covering search, pass, and greedy actions."""
    candidates: list[Pattern | None] = []
    seen: set[tuple] = set()
    for pattern in enumerate_search_candidates(
        state,
        player,
        max_candidates=max_actions,
    ):
        key = observable_key(pattern)
        if key not in seen:
            candidates.append(pattern)
            seen.add(key)

    if state.table:
        candidates.append(None)
        seen.add(PASS_ACTION)

    greedy = smallest_legal_pattern(state, player)
    if greedy is not None and observable_key(greedy) not in seen:
        candidates.append(greedy)
    return candidates


def _arm_key(pattern: Pattern | None) -> tuple:
    return PASS_ACTION if pattern is None else observable_key(pattern)


def _ranking_score(arm: _RootArm, prior_weight: float) -> float:
    """Use style as a diminishing tie-breaker, never as a hard veto."""
    if not arm.values:
        return -math.inf
    prior_adjustment = prior_weight * (arm.prior - 1.0) / max(2.0, arm.visits)
    return arm.mean_value + prior_adjustment


def root_action_search(
    state: GameState,
    player: int,
    *,
    rng: random.Random,
    iterations: int = 32,
    time_budget_ms: int = 0,
    max_actions: int = 6,
    rollout_strategy: int = 1,
    rollout_max_turns: int = 40,
    prior_weight: float = 0.18,
    style: SearchStyle | None = None,
    adaptive: bool = False,
    min_samples: int = 2,
    finalists: int = 2,
) -> SearchResult:
    """Evaluate root actions with paired worlds and optional successive halving.

    ``iterations`` counts action evaluations, matching the total-rollout budget
    used by tree search.  A hidden world is sampled once per round and copied
    for every active action, so comparisons within that round are paired.
    """
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if max_actions <= 0:
        raise ValueError("max_actions must be positive")
    if rollout_max_turns <= 0:
        raise ValueError("rollout_max_turns must be positive")
    if min_samples <= 0 or finalists <= 0:
        raise ValueError("min_samples and finalists must be positive")
    if player != state.current_player():
        raise ValueError(
            f"player {player} is not to act (current player is {state.current_player()})"
        )

    search_style = style or SearchStyle()
    patterns = root_action_candidates(state, player, max_actions=max_actions)
    arms = [
        _RootArm(
            key=_arm_key(pattern),
            pattern=pattern,
            prior=_action_prior(state, player, pattern, search_style),
        )
        for pattern in patterns
    ]
    if not arms:
        return SearchResult(
            pattern=None,
            simulations=0,
            sampled_worlds=0,
            elapsed_seconds=0.0,
            actions=(),
            budget_limited=False,
        )

    started = time.perf_counter()
    deadline = started + time_budget_ms / 1000.0 if time_budget_ms > 0 else None
    active = list(arms)
    evaluations = 0
    sampled_worlds = 0
    next_halving_at = min_samples
    stopped_by_clock = False

    while evaluations < iterations and active:
        sampled_world = determinize(state, player, rng)
        sampled_worlds += 1
        completed_round = True
        # Rotate partial rounds so a clock cutoff does not always favour the
        # first candidate in the deterministic ordering.
        offset = (sampled_worlds - 1) % len(active)
        ordered = active[offset:] + active[:offset]
        for arm in ordered:
            if evaluations >= iterations:
                completed_round = False
                break
            if evaluations > 0 and deadline is not None and time.perf_counter() >= deadline:
                stopped_by_clock = True
                completed_round = False
                break
            sampled = clone_state_for_search(sampled_world)
            if not _apply_action(sampled, player, arm.pattern):
                continue
            value = simulate_state(
                sampled,
                player,
                rollout_strategy_level=rollout_strategy,
                max_turns=rollout_max_turns,
                copy_state=False,
            )
            arm.values.append(value)
            evaluations += 1
        if stopped_by_clock:
            break

        if (
            adaptive
            and completed_round
            and len(active) > finalists
            and min(arm.visits for arm in active) >= next_halving_at
        ):
            keep = max(finalists, math.ceil(len(active) / 2))
            active = sorted(
                active,
                key=lambda arm: _ranking_score(arm, prior_weight),
                reverse=True,
            )[:keep]
            next_halving_at *= 2

    visited = [arm for arm in arms if arm.visits]
    best = max(
        visited,
        key=lambda arm: _ranking_score(arm, prior_weight),
        default=None,
    )
    action_stats = tuple(
        ActionStatistics(
            action_key=arm.key,
            pattern=arm.pattern,
            visits=arm.visits,
            availability=sampled_worlds,
            mean_value=arm.mean_value,
            prior=arm.prior,
        )
        for arm in arms
    )
    return SearchResult(
        pattern=best.pattern if best is not None else None,
        simulations=evaluations,
        sampled_worlds=sampled_worlds,
        elapsed_seconds=time.perf_counter() - started,
        actions=action_stats,
        budget_limited=stopped_by_clock,
    )

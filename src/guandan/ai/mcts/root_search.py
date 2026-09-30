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
from typing import Sequence

from ...engine.hand import Pattern
from ...engine.state import GameState, clone_state_for_search
from ..candidates import (
    enumerate_legal_patterns,
    material_variants,
    pattern_key,
    smallest_legal_pattern,
)
from ..context import PublicTacticalContext
from ..match_value import round_value_span
from ..partner_model import sample_styles
from ..tactics import select_heuristic_action
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
    reference_actions: Sequence[Pattern | None] = (),
) -> list[Pattern | None]:
    """Return a deduplicated union covering search, pass, and greedy actions."""
    candidates: list[Pattern | None] = []
    seen: set[tuple] = set()
    for pattern in enumerate_search_candidates(
        state,
        player,
        max_candidates=max_actions,
    ):
        key = pattern_key(pattern)
        if key not in seen:
            candidates.append(pattern)
            seen.add(key)

    # A few alternate suits within an otherwise identical play may change
    # the remaining hand substantially.  They remain exact legal root moves.
    for base in tuple(candidates[:2]):
        if base is None:
            continue
        for variant in material_variants(state, player, base, limit=1):
            key = pattern_key(variant)
            if key not in seen:
                candidates.append(variant)
                seen.add(key)

    if state.table:
        candidates.append(None)
        seen.add(PASS_ACTION)

    greedy = smallest_legal_pattern(state, player)
    if greedy is not None and pattern_key(greedy) not in seen:
        candidates.append(greedy)
        seen.add(pattern_key(greedy))
    references = reference_actions or (select_heuristic_action(state, player, 2),)
    for tactical in references:
        tactical_key = _arm_key(tactical)
        if tactical_key not in seen:
            candidates.append(tactical)
            seen.add(tactical_key)
    return candidates


def _arm_key(pattern: Pattern | None) -> tuple:
    return PASS_ACTION if pattern is None else pattern_key(pattern)


def _ranking_score(
    arm: _RootArm, prior_weight: float, common_visits: int | None = None
) -> float:
    """Use style as a diminishing tie-breaker, never as a hard veto."""
    values = arm.values if common_visits is None else arm.values[:common_visits]
    if not values:
        return -math.inf
    # A one-standard-error style tie break is useful with a small number of
    # paired worlds: it avoids spending a bomb for a noisy 1-2% lead while
    # vanishing as the evidence grows.
    # Raw priors include a deliberately large one-play-finish value; using
    # them directly can overwhelm an entire 0..1 rollout result at low counts.
    bounded_prior = math.tanh(math.log(max(0.01, arm.prior)))
    prior_adjustment = prior_weight * bounded_prior / math.sqrt(max(2.0, len(values)))
    return sum(values) / len(values) + prior_adjustment


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
    reference_actions: Sequence[Pattern | None] = (),
    heterogeneous_rollouts: bool = False,
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

    started = time.perf_counter()
    deadline = started + time_budget_ms / 1000.0 if time_budget_ms > 0 else None
    search_style = style or SearchStyle()
    prior_weight *= round_value_span(state)
    patterns = root_action_candidates(
        state, player, max_actions=max_actions, reference_actions=reference_actions
    )
    if rollout_strategy >= 3 and not state.table:
        # Reserve a control/support lead by replacing the weakest ordinary
        # representative; required finishes and reference moves remain present.
        context = PublicTacticalContext.from_state(state, player)
        legal = enumerate_legal_patterns(state, player)
        if legal:
            safety = min(legal[:48], key=lambda p: context.lead_adjustment(p))
            if all(p is None or pattern_key(p) != pattern_key(safety) for p in patterns):
                protected = {_arm_key(p) for p in reference_actions}
                protected.add(_arm_key(smallest_legal_pattern(state, player)))
                replace_at = next((
                    i for i, candidate in reversed(list(enumerate(patterns)))
                    if candidate is not None
                    and len(candidate.cards) != state.hand_size(player)
                    and _arm_key(candidate) not in protected
                ), None)
                if replace_at is not None:
                    patterns[replace_at] = safety
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

    active = list(arms)
    candidate_seconds = time.perf_counter() - started
    sampling_seconds = 0.0
    rollout_seconds = 0.0
    evaluations = 0
    sampled_worlds = 0
    next_halving_at = min_samples
    stopped_by_clock = False

    while evaluations < iterations and active:
        if deadline is not None and time.perf_counter() >= deadline:
            stopped_by_clock = True
            break
        sampling_started = time.perf_counter()
        sampled_world = determinize(state, player, rng)
        sampling_seconds += time.perf_counter() - sampling_started
        sampled_worlds += 1
        styles = sample_styles(state, rng) if heterogeneous_rollouts else None
        completed_round = True
        # Rotate partial rounds so a clock cutoff does not always favour the
        # first candidate in the deterministic ordering.
        offset = (sampled_worlds - 1) % len(active)
        ordered = active[offset:] + active[:offset]
        for arm in ordered:
            if evaluations >= iterations:
                completed_round = False
                break
            if deadline is not None and time.perf_counter() >= deadline:
                stopped_by_clock = True
                completed_round = False
                break
            rollout_started = time.perf_counter()
            sampled = clone_state_for_search(sampled_world)
            if not _apply_action(sampled, player, arm.pattern):
                continue
            value = simulate_state(
                sampled,
                player,
                rollout_strategy_level=rollout_strategy,
                max_turns=rollout_max_turns,
                copy_state=False,
                deadline=deadline,
                **({"styles": styles} if styles is not None else {}),
            )
            rollout_seconds += time.perf_counter() - rollout_started
            if deadline is not None and time.perf_counter() >= deadline:
                stopped_by_clock = True
                completed_round = False
                break
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
    # A partial final round may contain an unusually easy or hard hidden
    # world.  Compare all uniform arms on their common completed worlds so
    # extra samples at the clock boundary cannot bias the decision.
    common_visits = min(arm.visits for arm in arms) if not adaptive else None
    comparison_visits = common_visits if common_visits else None
    best = max(
        visited,
        key=lambda arm: _ranking_score(arm, prior_weight, comparison_visits),
        default=arms[0],
    )
    reference = next(
        (arm for arm in arms if reference_actions and arm.key == _arm_key(reference_actions[0])),
        None,
    )

    def paired_error(arm: _RootArm) -> float | None:
        if reference is None or not common_visits or common_visits < 2:
            return None
        differences = [
            value - baseline
            for value, baseline in zip(
                arm.values[:common_visits], reference.values[:common_visits]
            )
        ]
        mean = sum(differences) / common_visits
        return math.sqrt(
            sum((value - mean) ** 2 for value in differences)
            / (common_visits * (common_visits - 1))
        )

    action_stats = tuple(
        ActionStatistics(
            action_key=arm.key,
            pattern=arm.pattern,
            visits=arm.visits,
            availability=sampled_worlds,
            mean_value=(
                sum(arm.values[:comparison_visits]) / comparison_visits
                if comparison_visits else arm.mean_value
            ),
            prior=arm.prior,
            reference_key=reference.key if reference is not None else None,
            paired_standard_error=paired_error(arm),
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
        candidate_seconds=candidate_seconds,
        sampling_seconds=sampling_seconds,
        rollout_seconds=rollout_seconds,
        common_samples=common_visits or 0,
    )

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
from dataclasses import dataclass, field, replace
from typing import Any, Sequence

from ...engine.hand import Pattern
from ...engine.state import GameState, clone_state_for_search
from ..candidates import (
    enumerate_legal_patterns,
    is_bomb_pattern,
    material_variants,
    pattern_key,
    smallest_legal_pattern,
)
from ..config import DecisionBudget
from ..context import PublicTacticalContext
from ..match_value import round_value_span
from ..partner_model import sample_styles, style_distribution
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
    terminals: list[bool] = field(default_factory=list)

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


def ranked_candidates(
    state: GameState, player: int, patterns: list[Pattern | None],
    references: Sequence[Pattern | None], *, deadline: float | None,
) -> tuple[list[Pattern | None], dict]:
    """Atomically nominate one learned candidate, preserving the baseline on failure."""
    from ..action_ranker import (
        ActionObservation,
        RankingTimeout,
        check_deadline,
        load_model,
        score_actions,
    )

    started = time.perf_counter()
    report: dict[str, Any] = {"candidate_replaced": False, "reason": "unchanged"}
    try:
        check_deadline(deadline)
        model = load_model()
        check_deadline(deadline)
        observation = ActionObservation.from_state(state, player)
        legal: list[Pattern | None] = list(enumerate_legal_patterns(state, player))
        # Preserve the existing exact-material alternatives even when the rule
        # enumerator only represents one suit interpretation of a normal play.
        keys = {_arm_key(p) for p in legal}
        legal.extend(p for p in patterns if _arm_key(p) not in keys)
        if state.table and not any(p is None for p in legal):
            legal.append(None)
        check_deadline(deadline)
        scores = score_actions(observation, legal, model=model, deadline=deadline)
        if len(scores) != len(legal) or not all(math.isfinite(score) for score in scores):
            raise ValueError("invalid action-ranker scores")
        preferred = max(range(len(legal)), key=lambda i: scores[i]) if legal else None
        report.update(model_sha256=model.sha256, legal_actions=len(legal))
        if preferred is not None:
            action = legal[preferred]
            report["recommended_key"] = _arm_key(action)
            tactical = references or (select_heuristic_action(state, player, 2),)
            protected = {_arm_key(p) for p in tactical} | {PASS_ACTION}
            protected.add(_arm_key(smallest_legal_pattern(state, player)))
            replace_at = next((i for i, candidate in reversed(list(enumerate(patterns)))
                               if candidate is not None
                               and not is_bomb_pattern(candidate)
                               and len(candidate.cards) != state.hand_size(player)
                               and _arm_key(candidate) not in protected), None)
            check_deadline(deadline)
            if any(_arm_key(p) == _arm_key(action) for p in patterns):
                report["reason"] = "already_present"
            elif replace_at is None:
                report["reason"] = "protected_pool"
            else:
                updated = list(patterns)
                report["replaced_key"] = _arm_key(updated[replace_at])
                updated[replace_at] = action
                report.update(candidate_replaced=True, reason="nominated")
                return updated, {**report, "elapsed_seconds": time.perf_counter() - started}
    except RankingTimeout:
        report["reason"] = "budget_fallback"
    except Exception as error:
        # Optional research scoring must never discard the working baseline.
        report["reason"] = "model_fallback"
        report["error_type"] = type(error).__name__
    report["elapsed_seconds"] = time.perf_counter() - started
    return patterns, report


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
    partner_adaptation: bool = False,
    response_chain: bool = False,
    chain_worlds: int = 4,
    action_ranker: bool = False,
    reference_rollout_turns: int = 0,
    reference_refinement: bool = False,
    _candidate_actions: Sequence[Pattern | None] | None = None,
    decision_budget: DecisionBudget | None = None,
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
    if not 0 <= reference_rollout_turns <= rollout_max_turns:
        raise ValueError("reference rollout turns must fit the rollout horizon")
    if reference_rollout_turns and (heterogeneous_rollouts or partner_adaptation):
        raise ValueError("reference rollouts cannot be combined with style adaptation")
    if player != state.current_player():
        raise ValueError(
            f"player {player} is not to act (current player is {state.current_player()})"
        )
    if reference_refinement:
        if adaptive or rollout_strategy >= 3 or reference_rollout_turns or heterogeneous_rollouts or partner_adaptation or response_chain or action_ranker:
            raise ValueError("reference refinement requires an unmodified uniform root search")
        return _refined_search(
            state, player, rng=rng, iterations=iterations, time_budget_ms=time_budget_ms,
            max_actions=max_actions, rollout_strategy=rollout_strategy,
            rollout_max_turns=rollout_max_turns, prior_weight=prior_weight,
            style=style, reference_actions=reference_actions, decision_budget=decision_budget,
        )

    started = time.perf_counter()
    clock = decision_budget or DecisionBudget.start(time_budget_ms, started=started)
    deadline = clock.deadline
    search_style = style or SearchStyle()
    prior_weight *= round_value_span(state)
    patterns = list(_candidate_actions) if _candidate_actions is not None else root_action_candidates(
        state, player, max_actions=max_actions, reference_actions=reference_actions
    )
    probabilities = style_distribution(state) if partner_adaptation or heterogeneous_rollouts else None
    chain_report = None
    if response_chain:
        from ..response_chain import action_key, chain_candidates, evaluate_responses

        chain_started = time.perf_counter()
        chain_deadline = clock.slice(0.10).deadline
        pool = chain_candidates(state, player, reference_actions, limit=max_actions, deadline=chain_deadline)
        reports, chain_report = evaluate_responses(
            state, player, pool, rng=rng, worlds=chain_worlds, deadline=chain_deadline,
            probabilities=probabilities, partner_adaptation=partner_adaptation,
            rollout_strategy=rollout_strategy,
        )
        chain_report["elapsed_seconds"] = time.perf_counter() - chain_started
        if reports:
            preferred = max(pool, key=lambda p: reports[action_key(p)].value)
            protected = {_arm_key(p) for p in reference_actions}
            protected.add(_arm_key(smallest_legal_pattern(state, player)))
            if all(_arm_key(p) != _arm_key(preferred) for p in patterns):
                replace_at = next((i for i, p in reversed(list(enumerate(patterns)))
                                   if p is not None and len(p.cards) != state.hand_size(player)
                                   and _arm_key(p) not in protected), None)
                if replace_at is not None:
                    patterns[replace_at] = preferred
                    chain_report["candidate_replaced"] = True
        chain_report.setdefault("candidate_replaced", False)
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
    ranker_report = None
    if action_ranker:
        ranker_deadline = clock.slice(0.05).deadline
        patterns, ranker_report = ranked_candidates(
            state, player, patterns, reference_actions, deadline=ranker_deadline,
        )
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
    discarded_rollouts = 0
    reference_memo: dict | None = {} if reference_rollout_turns else None

    while evaluations < iterations and active:
        if deadline is not None and time.perf_counter() >= deadline:
            stopped_by_clock = True
            break
        sampling_started = time.perf_counter()
        sampled_world = determinize(state, player, rng)
        sampling_seconds += time.perf_counter() - sampling_started
        sampled_worlds += 1
        styles = sample_styles(state, rng, probabilities) if heterogeneous_rollouts or partner_adaptation else None
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
            rollout_options: dict[str, Any] = {}
            if styles is not None:
                rollout_options["styles"] = styles
            if partner_adaptation:
                rollout_options["partner_adaptation"] = True
            if reference_rollout_turns:
                rollout_options["reference_rollout_turns"] = reference_rollout_turns
                rollout_options["reference_memo"] = reference_memo
            value = simulate_state(
                sampled,
                player,
                rollout_strategy_level=rollout_strategy,
                max_turns=rollout_max_turns,
                copy_state=False,
                deadline=deadline,
                **rollout_options,
            )
            rollout_seconds += time.perf_counter() - rollout_started
            if deadline is not None and time.perf_counter() >= deadline:
                stopped_by_clock = True
                completed_round = False
                discarded_rollouts += 1
                break
            arm.values.append(value)
            arm.terminals.append(sampled.finished)
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
        terminal_rollouts=sum(sum(arm.terminals) for arm in arms),
        cutoff_rollouts=sum(sum(not terminal for terminal in arm.terminals) for arm in arms),
        discarded_rollouts=discarded_rollouts,
        terminal_common_samples=sum(all(arm.terminals[index] for arm in arms)
                                    for index in range(common_visits or 0)),
        partner_probabilities=probabilities or (),
        response_chain=chain_report,
        action_ranker=ranker_report,
    )


def _refined_search(
    state: GameState, player: int, *, rng: random.Random, iterations: int,
    time_budget_ms: int, max_actions: int, rollout_strategy: int, rollout_max_turns: int,
    prior_weight: float, style: SearchStyle | None,
    reference_actions: Sequence[Pattern | None],
    decision_budget: DecisionBudget | None = None,
) -> SearchResult:
    """Reserve half the work/clock for an independently paired expert challenge.

    Only the fast-search winner and tactical reference enter the second phase.
    Its common completed worlds entirely replace their coarse value estimates.
    At most eight pairs keep fixed-work evaluation near the production clock.
    Fewer than six pairs retain the tactical action; the strategy still applies
    its original payoff/confidence/bomb/pass guards to completed refinements.
    """
    started = time.perf_counter()
    clock = decision_budget or DecisionBudget.start(time_budget_ms, started=started)
    reference = reference_actions[0] if reference_actions else select_heuristic_action(state, player, 2)
    base = root_action_search(
        state, player, rng=rng, iterations=max(1, iterations // 2),
        time_budget_ms=max(1, time_budget_ms // 2) if time_budget_ms > 0 else 0,
        max_actions=max_actions, rollout_strategy=rollout_strategy,
        rollout_max_turns=rollout_max_turns, prior_weight=prior_weight,
        style=style, reference_actions=(reference,), decision_budget=clock.slice(0.5),
    )
    report = {"base_simulations": base.simulations, "base_common_samples": base.common_samples,
              "base_seconds": base.elapsed_seconds, "challenger_key": _arm_key(base.pattern),
              "reference_key": _arm_key(reference), "refinement_simulations": 0,
              "refinement_common_samples": 0, "max_common_samples": 8,
              "reason": "agrees_with_reference"}
    if _arm_key(base.pattern) == _arm_key(reference):
        return replace(base, elapsed_seconds=time.perf_counter() - started, reference_refinement=report)
    remaining_iterations = iterations - base.simulations
    remaining_ms = clock.remaining_ms()
    if remaining_iterations < 12 or (time_budget_ms > 0 and remaining_ms < 100):
        report["reason"] = "insufficient_budget"
        return replace(base, pattern=reference, elapsed_seconds=time.perf_counter() - started,
                       reference_refinement=report)
    refined = root_action_search(
        state, player, rng=rng, iterations=min(remaining_iterations, 16),
        time_budget_ms=remaining_ms, max_actions=2,
        rollout_strategy=rollout_strategy, rollout_max_turns=120,
        prior_weight=prior_weight, style=style, reference_actions=(reference,),
        reference_rollout_turns=8, _candidate_actions=(base.pattern, reference), decision_budget=clock,
    )
    report.update(refinement_simulations=refined.simulations,
                  refinement_common_samples=refined.common_samples,
                  refinement_seconds=refined.elapsed_seconds,
                  reason="completed" if refined.common_samples >= 6 else "insufficient_pairs")
    return replace(
        refined, pattern=refined.pattern if refined.common_samples >= 6 else reference,
        simulations=base.simulations + refined.simulations,
        sampled_worlds=base.sampled_worlds + refined.sampled_worlds,
        elapsed_seconds=time.perf_counter() - started,
        budget_limited=base.budget_limited or refined.budget_limited,
        candidate_seconds=base.candidate_seconds + refined.candidate_seconds,
        sampling_seconds=base.sampling_seconds + refined.sampling_seconds,
        rollout_seconds=base.rollout_seconds + refined.rollout_seconds,
        terminal_rollouts=base.terminal_rollouts + refined.terminal_rollouts,
        cutoff_rollouts=base.cutoff_rollouts + refined.cutoff_rollouts,
        discarded_rollouts=base.discarded_rollouts + refined.discarded_rollouts,
        reference_refinement=report,
    )

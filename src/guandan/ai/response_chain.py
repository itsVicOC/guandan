"""Bounded, paired action chains with observed trick ownership."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Sequence

from ..engine.hand import Pattern
from ..engine.state import GameState, clone_state_for_search, pass_turn, play_pattern
from .candidates import enumerate_legal_patterns, pattern_key
from .context import PublicTacticalContext
from .mcts.determinize import determinize
from .mcts.information_set import PASS_ACTION
from .partner_model import sample_styles
from .valuation import estimate_pattern_cost


@dataclass(frozen=True)
class ChainStatistics:
    samples: int
    value: float
    own_control: float
    partner_control: float
    opponent_control: float
    unresolved: float


def action_key(pattern: Pattern | None) -> tuple:
    return PASS_ACTION if pattern is None else pattern_key(pattern)


def chain_candidates(
    state: GameState,
    player: int,
    references: Sequence[Pattern | None],
    *,
    limit: int,
    deadline: float | None = None,
) -> list[Pattern | None]:
    """Keep the reference/pass and inexpensive public support alternatives."""
    chosen: dict[tuple, Pattern | None] = {}
    for pattern in references:
        if pattern is not None or state.table:
            chosen[action_key(pattern)] = pattern
    if state.table:
        chosen[PASS_ACTION] = None
    if deadline is not None and time.perf_counter() >= deadline:
        return list(chosen.values())
    legal = enumerate_legal_patterns(state, player)
    # First material-rank the pool; only score 48 representatives publicly.
    material = []
    for pattern in legal:
        if deadline is not None and time.perf_counter() >= deadline:
            return list(chosen.values())
        material.append((estimate_pattern_cost(state, player, pattern), pattern))
    if deadline is not None and time.perf_counter() >= deadline:
        return list(chosen.values())
    context = PublicTacticalContext.from_state(state, player)
    ranked = []
    for cost, pattern in sorted(material, key=lambda item: item[0])[:48]:
        if deadline is not None and time.perf_counter() >= deadline:
            break
        score = 0.13 * cost
        score += (
            context.lead_adjustment(pattern)
            if not state.table
            else 12.0 * context.finish_risk(pattern)
        )
        if len(pattern.cards) == state.hand_size(player):
            score -= 100.0
        ranked.append((score, pattern))
    for _, pattern in sorted(ranked, key=lambda item: item[0]):
        if len(chosen) >= limit:
            break
        chosen.setdefault(action_key(pattern), pattern)
    return list(chosen.values())


def evaluate_responses(
    state: GameState,
    player: int,
    patterns: Sequence[Pattern | None],
    *,
    rng: random.Random,
    worlds: int,
    deadline: float | None = None,
    probabilities: tuple[tuple[float, float, float], ...] | None = None,
    partner_adaptation: bool = False,
    rollout_strategy: int = 2,
) -> tuple[dict[tuple, ChainStatistics], dict]:
    """Apply the root move and up to eight actual replies, including counters.

    A time-interrupted round contributes nothing, even for earlier candidates.
    The action horizon is a deliberate approximation, never a solved endgame.
    """
    from .mcts.search import _evaluate_result, _rollout_select_pattern, planned_position_value

    totals = [[0.0] * 5 for _ in patterns]
    completed = 0
    interrupted = False
    for _ in range(worlds):
        if deadline is not None and time.perf_counter() >= deadline:
            interrupted = True
            break
        world = determinize(state, player, rng)
        styles = (
            sample_styles(state, rng, probabilities) if partner_adaptation else ("balanced",) * 4
        )
        values = []
        for pattern in patterns:
            if deadline is not None and time.perf_counter() >= deadline:
                interrupted = True
                break
            sim = clone_state_for_search(world)
            if pattern is None:
                pass_turn(sim, player)
            else:
                play_pattern(sim, player, pattern)
            for _step in range(8):
                if deadline is not None and time.perf_counter() >= deadline:
                    interrupted = True
                    break
                if sim.finished or not sim.table:
                    break
                actor = sim.current_player()
                reply = _rollout_select_pattern(
                    sim,
                    actor,
                    rollout_strategy_level=rollout_strategy,
                    style=styles[actor],
                    partner_adaptation=partner_adaptation,
                )
                if reply is None:
                    pass_turn(sim, actor)
                else:
                    play_pattern(sim, actor, reply)
            if deadline is not None and time.perf_counter() >= deadline:
                interrupted = True
            if interrupted:
                break
            # Only a resolved trick proves control. An available response or
            # an unresolved table top is not a successful recovery.
            owner = sim.current_player() if not sim.finished and not sim.table else None
            value = (
                _evaluate_result(sim, player)
                if sim.finished or sim.finish_order
                else planned_position_value(sim, player)
            )
            if deadline is not None and time.perf_counter() >= deadline:
                interrupted = True
                break
            values.append(
                (
                    value,
                    float(owner == player),
                    float(owner == (player + 2) % 4),
                    float(owner is not None and owner % 2 != player % 2),
                    float(owner is None and not sim.finished),
                )
            )
        if interrupted:
            break
        for total, row in zip(totals, values):
            for index, value in enumerate(row):
                total[index] += value
        completed += 1
    reports = (
        {
            action_key(pattern): ChainStatistics(completed, *(value / completed for value in total))
            for pattern, total in zip(patterns, totals)
        }
        if completed >= 3
        else {}
    )
    reason = (
        "budget_limited"
        if interrupted
        else "complete"
        if completed >= 3 and completed == worlds
        else "insufficient_worlds"
    )
    return reports, {
        "completed_worlds": completed,
        "requested_worlds": worlds,
        "used": bool(reports),
        "reason": reason,
        "horizon": 8,
        "ownership": {
            str(key): {
                "own": row.own_control,
                "partner": row.partner_control,
                "opponent": row.opponent_control,
                "unresolved": row.unresolved,
            }
            for key, row in reports.items()
        },
    }

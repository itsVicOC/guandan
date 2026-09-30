"""Small-deal, deadline-bounded team search over sampled hidden worlds."""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from ...engine.events import Pass, TributeReturned, TributeSent, TurnPlayed
from ...engine.hand import Pattern
from ...engine.state import GameState, clone_state_for_search, team_of
from ...engine.trick import current_top_player
from ..candidates import enumerate_exact_small_hand_patterns, pattern_key
from ..context import PublicTacticalContext
from ..match_value import round_value_span
from ..tactics import select_heuristic_action
from .determinize import determinize
from .information_set import PASS_ACTION, ActionKey, ActionStatistics, _apply_action
from .search import _evaluate_result, _rollout_select_pattern


class _OutOfTime(Exception):
    pass


class _DepthLimit(_OutOfTime):
    pass


class _Unsolved:
    pass


@dataclass
class _Entry:
    value: float
    bound: str
    best_key: tuple | None = None


@dataclass
class _Budget:
    deadline: float
    nodes_left: int
    cache: dict[tuple, _Entry] = field(default_factory=dict)
    cache_hits: int = 0
    information_safe: bool = False

    def consume(self) -> None:
        if self.nodes_left <= 0 or time.perf_counter() >= self.deadline:
            raise _OutOfTime
        self.nodes_left -= 1

    def check_time(self) -> None:
        if time.perf_counter() >= self.deadline:
            raise _OutOfTime


def _key(state: GameState, depth: int) -> tuple:
    return (
        tuple(tuple(sorted(hand)) for hand in state.hands),
        tuple(state.table),
        tuple(sorted(state.passed_players)),
        state.turn_index,
        state.leader,
        current_top_player(state),
        tuple(state.finish_order),
        state.level, state.wild_card, tuple(state.team_levels),
        tuple(state.a_failure_counts), state.ruleset_version,
        depth,
    )


def _actions(state: GameState, player: int, budget: _Budget | None = None) -> list[Pattern | None]:
    candidates: dict[tuple, Pattern] = {}
    for pattern in enumerate_exact_small_hand_patterns(state, player, check=budget.check_time if budget else None):
        candidates.setdefault(pattern_key(pattern), pattern)
    actions: list[Pattern | None] = list(candidates.values())
    actions.sort(
        key=lambda p: (
            p is None or len(p.cards) != state.hand_size(player),
            -len(p.cards) if p is not None else 0,
        )
    )
    if state.table:
        actions.append(None)
    return actions


def _minimax(
    state: GameState,
    root_player: int,
    depth: int,
    budget: _Budget,
    alpha: float,
    beta: float,
) -> float:
    budget.consume()
    if state.finished:
        return _evaluate_result(state, root_player)
    if depth <= 0:
        # A heuristic leaf is not a solved game. Even a future caller using
        # too small a depth must not accidentally get an "exact" result.
        raise _DepthLimit
    # Actor-local policy continuations depend on public history as well as
    # legal state. Full-information minimax needs only the game state.
    key = (_key(state, depth), team_of(root_player), tuple(e for e in state.history if isinstance(e, (TurnPlayed, Pass, TributeSent, TributeReturned))) if budget.information_safe else ())
    original_alpha, original_beta = alpha, beta
    cached = budget.cache.get(key)
    if cached is not None:
        budget.cache_hits += 1
        if cached.bound == "EXACT":
            return cached.value
        if cached.bound == "LOWER":
            alpha = max(alpha, cached.value)
        else:
            beta = min(beta, cached.value)
        if alpha >= beta:
            return cached.value
    player = state.current_player()
    maximizing = team_of(player) == team_of(root_player)
    value = 0.0 if maximizing else 1.0
    actions = (
        [_rollout_select_pattern(state, player, rollout_strategy_level=2)]
        if budget.information_safe else _actions(state, player, budget)
    )
    if cached is not None and cached.best_key is not None:
        actions.sort(key=lambda action: (PASS_ACTION if action is None else pattern_key(action)) != cached.best_key)
    best_key = None
    for action in actions:
        child = clone_state_for_search(state)
        if not _apply_action(child, player, action):
            continue
        result = _minimax(child, root_player, depth - 1, budget, alpha, beta)
        if maximizing:
            if best_key is None or result > value:
                best_key = PASS_ACTION if action is None else pattern_key(action)
            value = max(value, result)
            alpha = max(alpha, value)
        else:
            if best_key is None or result < value:
                best_key = PASS_ACTION if action is None else pattern_key(action)
            value = min(value, result)
            beta = min(beta, value)
        if beta <= alpha:
            break
    bound = "UPPER" if value <= original_alpha else "LOWER" if value >= original_beta else "EXACT"
    # The extrema are exact even after a cutoff: no utility is outside 0..1.
    if (maximizing and value == 1.0) or (not maximizing and value == 0.0) or budget.information_safe:
        bound = "EXACT"
    budget.cache[key] = _Entry(value, bound, best_key)
    return value


@dataclass(frozen=True)
class EndgameSearchResult:
    pattern: Pattern | None
    actions: tuple[ActionStatistics, ...]
    common_samples: int
    nodes: int
    elapsed_seconds: float
    complete: bool
    exact: bool
    reason: str
    cache_hits: int = 0
    continuation: str = "full_information"


def search_endgame(
    state: GameState,
    player: int,
    *,
    rng: random.Random,
    deadline: float,
    max_actions: int = 10,
    worlds: int = 8,
    min_worlds: int = 6,
    max_nodes: int = 30000,
    confidence_guard: bool = True,
    team_tactics: bool = True,
    information_safe: bool = False,
) -> EndgameSearchResult:
    """Compare terminal team values on common worlds, not heuristic leaves.

    Every root action is evaluated in the same independently sampled worlds.
    Full-information minimax is confined to those hypothetical worlds; the
    actual hands of the other players are never read.
    """
    if min(worlds, min_worlds, max_nodes, max_actions) <= 0:
        raise ValueError("endgame limits must be positive")
    if player != state.current_player():
        raise ValueError("endgame player is not to act")
    started = time.perf_counter()
    budget = _Budget(deadline=deadline, nodes_left=max_nodes, information_safe=information_safe)
    try:
        actions = _actions(state, player, budget)
        budget.check_time()
    except _OutOfTime:
        return EndgameSearchResult(None, (), 0, 0, time.perf_counter() - started, False, False, "enumeration_budget_limited")
    # The reference only needs to be an already-enumerated legal move. Avoid
    # an uninterruptible, cold hand-plan computation before search starts.
    reference = next((a for a in actions if a is not None and len(a.cards) == state.hand_size(player)), None)
    if reference is None and time.perf_counter() < deadline:
        reference = select_heuristic_action(state, player, 0)
    def key_of(action: Pattern | None) -> ActionKey:
        return PASS_ACTION if action is None else pattern_key(action)
    reference_index = next((i for i, action in enumerate(actions) if key_of(action) == key_of(reference)), 0)
    context = PublicTacticalContext.from_state(state, player)
    exact = (
        len(context.unseen) == sum(context.sizes[seat] for seat in range(4) if seat != player)
        and sum(context.sizes[seat] > len(context.known[seat]) for seat in range(4) if seat != player) <= 1
    )
    values: list[list[float]] = [[] for _ in actions]
    reason = "policy_sampled" if information_safe else "sampled"
    try:
        for _ in range(1 if exact else worlds):
            budget.consume()
            sampled = determinize(state, player, rng)
            round_values = []
            for action in actions:
                child = clone_state_for_search(sampled)
                if not _apply_action(child, player, action):
                    raise ValueError("invalid endgame root action")
                # At most three passes can separate card-removing plays;
                # this bound therefore reaches every possible terminal path.
                round_values.append(_minimax(child, player, 4 * sum(map(len, child.hands)) + 4, budget, 0.0, 1.0))
            for index, value in enumerate(round_values):
                values[index].append(value)
    except _DepthLimit:
        reason = "depth_limit"
    except _OutOfTime:
        reason = "budget_limited"
    except ValueError:
        reason = "invalid_public_state"
    common = min(map(len, values), default=0)

    def error(index: int) -> float | None:
        if common < 2:
            return None
        differences = [a - b for a, b in zip(values[index], values[reference_index])]
        mean = sum(differences) / common
        return math.sqrt(sum((d - mean) ** 2 for d in differences) / (common * (common - 1)))

    stats = tuple(ActionStatistics(
        action_key=key_of(action), pattern=action, visits=common, availability=common,
        mean_value=sum(values[index]) / common if common else 0.5, prior=1.0,
        reference_key=key_of(actions[reference_index]), paired_standard_error=error(index),
    ) for index, action in enumerate(actions))
    complete = bool(actions) and common >= (1 if exact else min_worlds)
    chosen = max(range(len(actions)), key=lambda i: (stats[i].mean_value, i == reference_index), default=reference_index)
    if complete and confidence_guard and not exact and chosen != reference_index:
        required = max(0.04 * round_value_span(state), 1.64 * (error(chosen) or 0.0))
        if stats[chosen].mean_value - stats[reference_index].mean_value < required:
            chosen = reference_index
            reason = "tactical_guard"
    return EndgameSearchResult(
        actions[chosen] if actions else reference, stats, common,
        max_nodes - budget.nodes_left, time.perf_counter() - started,
        complete, exact and complete and not information_safe,
        "exact" if exact and complete and not information_safe else reason,
        budget.cache_hits, "actor_local_policy" if information_safe else "full_information",
    )


def solve_endgame(
    state: GameState, player: int, *, rng: random.Random, deadline: float,
    max_actions: int = 10, worlds: int = 8, min_worlds: int = 6, max_nodes: int = 30000,
    confidence_guard: bool = True, team_tactics: bool = True,
    information_safe: bool = False,
    reports: list[EndgameSearchResult] | None = None,
) -> Pattern | _Unsolved | None:
    """Compatibility action API; reports distinguish sampling from exact play."""
    result = search_endgame(
        state, player, rng=rng, deadline=deadline, max_actions=max_actions,
        worlds=worlds, min_worlds=min_worlds, max_nodes=max_nodes,
        confidence_guard=confidence_guard, team_tactics=team_tactics,
        information_safe=information_safe,
    )
    if reports is not None:
        reports.append(result)
    return result.pattern if result.complete else UNSOLVED


UNSOLVED = _Unsolved()

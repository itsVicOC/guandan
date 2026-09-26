"""Small-deal, deadline-bounded team search over sampled hidden worlds."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from ...engine.hand import Pattern
from ...engine.state import GameState, clone_state_for_search, team_of
from ...engine.trick import current_top_player
from ..candidates import enumerate_legal_patterns, pattern_key
from .determinize import determinize
from .information_set import _apply_action
from .root_search import root_action_candidates
from .search import _evaluate_result


class _OutOfTime(Exception):
    pass


class _Unsolved:
    pass


@dataclass
class _Budget:
    deadline: float
    nodes_left: int
    cache: dict[tuple, float] = field(default_factory=dict)

    def consume(self) -> None:
        self.nodes_left -= 1
        if self.nodes_left < 0 or time.perf_counter() >= self.deadline:
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
        depth,
    )


def _actions(state: GameState, player: int) -> list[Pattern | None]:
    candidates: dict[tuple, Pattern] = {}
    for pattern in enumerate_legal_patterns(state, player):
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
    if state.finished or depth == 0:
        return _evaluate_result(state, root_player)
    key = _key(state, depth)
    cached = budget.cache.get(key)
    if cached is not None:
        return cached
    player = state.current_player()
    maximizing = team_of(player) == team_of(root_player)
    original_alpha, original_beta = alpha, beta
    value = 0.0 if maximizing else 1.0
    cut = False
    for action in _actions(state, player):
        child = clone_state_for_search(state)
        if not _apply_action(child, player, action):
            continue
        result = _minimax(child, root_player, depth - 1, budget, alpha, beta)
        if maximizing:
            value = max(value, result)
            alpha = max(alpha, value)
        else:
            value = min(value, result)
            beta = min(beta, value)
        if beta <= alpha:
            cut = True
            break
    # A fail-low result can be an upper bound even without a local cutoff:
    # its descendants may have pruned against the inherited alpha.  Only
    # reuse exact values, never such bounds in another search window.
    if not cut and original_alpha < value < original_beta:
        budget.cache[key] = value
    return value


def solve_endgame(
    state: GameState,
    player: int,
    *,
    rng: random.Random,
    deadline: float,
    max_actions: int = 10,
    worlds: int = 2,
    max_nodes: int = 30000,
) -> Pattern | _Unsolved | None:
    """Return the best sampled-world action, or ``UNSOLVED`` at the limit.

    Every root action is evaluated in the same independently sampled worlds.
    Full-information minimax is confined to those hypothetical worlds; the
    actual hands of the other players are never read.
    """
    actions = root_action_candidates(state, player, max_actions=max_actions)
    if not actions:
        return UNSOLVED
    totals = [0.0] * len(actions)
    budget = _Budget(deadline=deadline, nodes_left=max_nodes)
    try:
        for _ in range(worlds):
            sampled = determinize(state, player, rng)
            for index, action in enumerate(actions):
                child = clone_state_for_search(sampled)
                if not _apply_action(child, player, action):
                    return UNSOLVED
                totals[index] += _minimax(child, player, 32, budget, 0.0, 1.0)
    except (_OutOfTime, ValueError):
        return UNSOLVED
    return actions[max(range(len(actions)), key=lambda index: totals[index])]


UNSOLVED = _Unsolved()

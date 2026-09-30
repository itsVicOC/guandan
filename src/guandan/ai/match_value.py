"""Offline, symmetric continuation values for the three-attempt A match.

The table is a small empirical round-transition model, not a solved game or
a human win probability. Runtime decisions only load it; value iteration and
policy fitting belong to scripts/fit_match_value.py.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from ..engine.state import GameState

MODEL_PATH = Path(__file__).with_name("profiles") / "match_value.json"
OUTCOMES = tuple((team, place) for team in (0, 1) for place in (2, 3, 4))
SCORES = (*((level, 0) for level in range(2, 14)), (14, 0), (14, 1), (14, 2))


def successor(
    levels: Sequence[int], failures: Sequence[int], head_team: int, partner_place: int,
) -> tuple[tuple[int, int], tuple[int, int], int | None]:
    """Pure ruleset-3 score transition, also used to build offline labels."""
    if head_team not in (0, 1) or partner_place not in (2, 3, 4):
        raise ValueError("invalid round outcome")
    new_levels, counts = list(levels), list(failures)
    if levels[head_team] == 14 and partner_place != 4:
        new_levels[head_team] = 2
        return (new_levels[0], new_levels[1]), (counts[0], counts[1]), head_team
    new_levels[head_team] = min(14, levels[head_team] + 5 - partner_place)
    for team in (0, 1):
        if levels[team] == 14:
            counts[team] += 1
            if counts[team] >= 3:
                new_levels[team], counts[team] = 2, 0
        elif new_levels[team] != 14:
            counts[team] = 0
    return (new_levels[0], new_levels[1]), (counts[0], counts[1]), None


def table_key(levels: Sequence[int], failures: Sequence[int], head_team: int, place: int) -> str:
    counts = tuple(failures[t] if levels[t] == 14 else 0 for t in (0, 1))
    return ",".join(map(str, (levels[0], counts[0], levels[1], counts[1], head_team, place)))


@lru_cache(maxsize=1)
def load_model() -> dict:
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    if model["schema"] != 1 or model["ruleset_version"] != 3:
        raise ValueError("incompatible match-value model")
    return model


def continuation_value(
    levels: Sequence[int], failures: Sequence[int], head_team: int, place: int, root_team: int,
) -> float:
    """Expected future match utility after a completed, nonterminal round."""
    value = float(load_model()["continuation"][table_key(levels, failures, head_team, place)])
    return value if root_team == 0 else 1.0 - value


def outcome_value(state: GameState, root_team: int, head_team: int, place: int) -> float:
    levels, counts, winner = successor(state.team_levels, state.a_failure_counts, head_team, place)
    if winner is not None:
        return float(winner == root_team)
    return continuation_value(levels, counts, head_team, place, root_team)


def round_value_span(state: GameState) -> float:
    """Scale priors and practical gain floors to the current payoff units."""
    if state.ruleset_version < 3:
        return 1.0
    values = [outcome_value(state, 0, team, place) for team, place in OUTCOMES]
    return max(0.02, max(values) - min(values))


def terminal_match_value(state: GameState, root_team: int) -> float:
    if state.match_finished and state.winner_team is not None:
        return float(state.winner_team == root_team)
    order = list(state.finish_order)
    order.extend(seat for seat in range(4) if seat not in order)
    head = order[0]
    place = order.index((head + 2) % 4) + 1
    if state.team_levels_final is None:
        return outcome_value(state, root_team, head % 2, place)
    return continuation_value(state.team_levels_final, state.a_failure_counts, head % 2, place, root_team)


def outcome_probabilities(features: Sequence[float]) -> tuple[float, ...]:
    """Six rank outcomes; enforce complementarity under team exchange."""
    weights = load_model()["rank_weights"]
    if len(features) + 1 != len(weights[0]):
        raise ValueError("incompatible rank features")

    def softmax(sign: float) -> list[float]:
        x = (1.0, *(sign * value for value in features))
        logits = [sum(w * v for w, v in zip(row, x)) for row in weights]
        offset = max(logits)
        values = [math.exp(value - offset) for value in logits]
        total = sum(values)
        return [value / total for value in values]

    direct, exchanged = softmax(1.0), softmax(-1.0)
    return tuple((direct[i] + exchanged[(i + 3) % 6]) / 2.0 for i in range(6))


def build_continuation_table(
    transitions: dict[str, list[float]], *, tolerance: float = 1e-11,
) -> tuple[dict[str, float], int, float]:
    """Offline Bellman iteration over 1,350 score/tribute states.

    Each transition row is canonical to the previous head's team and its
    partner's place. Empirical rows include actual tribute and resist flows.
    """
    states = [
        (l0, c0, l1, c1, head, place)
        for l0, c0 in SCORES for l1, c1 in SCORES
        for head in (0, 1) for place in (2, 3, 4)
    ]
    indices = {state: i for i, state in enumerate(states)}
    branches: list[list[tuple[float, int | None, float]]] = []
    for l0, c0, l1, c1, previous, previous_place in states:
        level = (l0, l1)[previous]
        band = 0 if level <= 6 else 1 if level <= 10 else 2
        probabilities = transitions[f"{band},{previous_place}"]
        if len(probabilities) != 6 or abs(sum(probabilities) - 1.0) > 1e-8:
            raise ValueError("invalid round-transition probabilities")
        row = []
        for relative, (team, place) in enumerate(OUTCOMES):
            team ^= previous
            levels, counts, winner = successor((l0, l1), (c0, c1), team, place)
            index = None if winner is not None else indices[(levels[0], counts[0], levels[1], counts[1], team, place)]
            row.append((probabilities[relative], index, float(winner == 0)))
        branches.append(row)
    values = [0.5] * len(states)
    residual = math.inf
    for iteration in range(1, 2001):
        updated = [sum(p * (terminal if index is None else values[index]) for p, index, terminal in row) for row in branches]
        residual = max(abs(a - b) for a, b in zip(updated, values))
        values = updated
        if residual <= tolerance:
            return {",".join(map(str, state)): value for state, value in zip(states, values)}, iteration, residual
    raise RuntimeError("match continuation did not converge")

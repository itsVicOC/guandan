"""Small public-history style mixture for heterogeneous continuations."""

from __future__ import annotations

import random

from ..engine.events import Pass, TurnPlayed
from ..engine.rules.comparator import is_bomb_type
from ..engine.state import GameState, is_teammate
from .observation import ActorObservation

STYLES = ("balanced", "conservative", "shedding")


def style_probabilities(state: GameState, seat: int) -> tuple[float, float, float]:
    return _style_probabilities(ActorObservation.from_state(state, seat), seat)


def _style_probabilities(state: ActorObservation, seat: int) -> tuple[float, float, float]:
    # Shrink strongly to a mixed prior: a handful of plays is not enough to
    # infer a human's identity, skill, or private hand.
    weights = [6.0, 3.0, 3.0]
    top: int | None = None
    passed: set[int] = set()
    sizes = [27] * 4
    observations: list[tuple[float, float, float]] = []
    for event in state.history:
        if isinstance(event, TurnPlayed):
            leading = top is None
            urgent = any(0 < sizes[s] <= 3 for s in range(4) if not is_teammate(s, event.player))
            if event.player == seat:
                row = [0.0, 0.0, 0.0]
                if not urgent and event.hand_remaining > 0:
                    if is_bomb_type(event.pattern.type):
                        row[0] = 0.4
                    elif len(event.pattern.cards) >= 4:
                        row[2] = 0.8 if leading else 0.4
                    else:
                        row[0] = 0.2 if leading else 0.1
                observations.append((row[0], row[1], row[2]))
            sizes[event.player] = event.hand_remaining
            top = event.player
            if state.ruleset_version != 1:
                passed.clear()
        elif isinstance(event, Pass):
            if event.player == seat:
                urgent = top is not None and 0 < sizes[top] <= 3
                observations.append(
                    (
                        0.0,
                        0.15
                        if top is not None and not is_teammate(seat, top) and not urgent
                        else 0.0,
                        0.0,
                    )
                )
            passed.add(event.player)
            if top is not None and all(sizes[s] == 0 or s == top or s in passed for s in range(4)):
                top = None
                passed.clear()
    for age, evidence_row in enumerate(reversed(observations[-16:])):
        decay = 2.0 ** (-age / 8.0)
        for index, value in enumerate(evidence_row):
            weights[index] += decay * value
    total = sum(weights)
    return tuple(value / total for value in weights)  # type: ignore[return-value]


def style_distribution(state: GameState) -> tuple[tuple[float, float, float], ...]:
    """Compute once from real public history, before branching continuations."""
    observation = ActorObservation.from_state(state, state.turn_index)
    return tuple(_style_probabilities(observation, seat) for seat in range(4))


def sample_styles(
    state: GameState,
    rng: random.Random,
    probabilities: tuple[tuple[float, float, float], ...] | None = None,
) -> tuple[str, ...]:
    # Draw once per common world, so every candidate receives the same
    # partner/opponent execution style and action comparisons stay paired.
    distributions = probabilities if probabilities is not None else style_distribution(state)
    return tuple(rng.choices(STYLES, weights=weights, k=1)[0] for weights in distributions)

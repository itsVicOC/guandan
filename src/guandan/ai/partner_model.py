"""Small public-history style mixture for heterogeneous continuations."""
from __future__ import annotations

import random

from ..engine.events import Pass, TurnPlayed
from ..engine.rules.comparator import is_bomb_type
from ..engine.state import GameState, is_teammate

STYLES = ("balanced", "conservative", "shedding")


def style_probabilities(state: GameState, seat: int) -> tuple[float, float, float]:
    # Shrink strongly to a mixed prior: a handful of plays is not enough to
    # infer a human's identity, skill, or private hand.
    weights = [6.0, 3.0, 3.0]
    top: int | None = None
    observations = 0
    for event in state.history:
        if isinstance(event, TurnPlayed):
            top = event.player
            if event.player == seat:
                observations += 1
                if is_bomb_type(event.pattern.type):
                    weights[0] += 0.4
                elif len(event.pattern.cards) >= 4:
                    weights[2] += 0.8
                else:
                    weights[0] += 0.2
        elif isinstance(event, Pass) and event.player == seat and top is not None and not is_teammate(seat, top):
            weights[1] += 0.15
        if observations >= 16:
            break
    total = sum(weights)
    return tuple(value / total for value in weights)  # type: ignore[return-value]


def sample_styles(state: GameState, rng: random.Random) -> tuple[str, ...]:
    # Draw once per common world, so every candidate receives the same
    # partner/opponent execution style and action comparisons stay paired.
    return tuple(rng.choices(STYLES, weights=style_probabilities(state, seat), k=1)[0] for seat in range(4))

"""Offline-trained, actor-public root action ranking (never a win probability).

The observation deliberately has no GameState, deal seed or hidden hands.
Feature extraction uses counters only, not pattern enumeration or hand planning.
The optional model can nominate one root candidate; search still chooses the move.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from ..engine.card import Card
from ..engine.hand import Pattern, PatternType, comparison_rank, effective_rank
from ..engine.state import GameState
from .candidates import is_bomb_pattern
from .context import PublicTacticalContext
from .observation import ActorObservation

MODEL_PATH = Path(__file__).with_name("profiles") / "action_ranker_v1.json"
MODEL_SCHEMA = 1
FEATURE_VERSION = "public-action-interactions-v1"
_TYPES = tuple(PatternType)
_BASE_NAMES: tuple[str, ...] = (
    "pass", "cards", "strength", "bomb", "wild_used", "finish",
    "remaining", "singletons", "pairs", "triples", "bomb_groups",
    "broken_pairs", "broken_triples", "broken_bombs", "low_singletons",
    "control_remaining", "wild_remaining", "suited_links", "lost_suited_links",
    "larger_than_enemy", "fits_partner", "unseen_higher", "known_enemy_higher",
    "known_partner_higher",
)
_BASE_NAMES += tuple(f"type_{kind.name.lower()}" for kind in _TYPES)
_BASE_NAMES += tuple(f"used_suit_{suit}" for suit in range(6))
_CONTEXT_NAMES = (
    "partner_top", "enemy_top", "enemy_one", "enemy_two", "enemy_three",
    "partner_short", "head_placed", "level_difference", "own_a", "enemy_a",
    "own_a_failures", "enemy_a_failures",
)
FEATURE_NAMES = _BASE_NAMES + tuple(
    f"{base}*{context}" for context in _CONTEXT_NAMES for base in _BASE_NAMES
)


class RankingTimeout(TimeoutError):
    """A whole ranking stage must be discarded after its deadline."""


def check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.perf_counter() >= deadline:
        raise RankingTimeout("action ranking deadline exceeded")


@dataclass(frozen=True)
class ActionObservation:
    """An immutable view relative to the actor, in counterclockwise seat order."""

    hand: tuple[Card, ...]
    wild: Card | None
    level: int
    sizes: tuple[int, ...]
    levels: tuple[int, int]
    a_failures: tuple[int, int]
    top: Pattern | None
    top_relation: int  # 0 lead, 1 own, 2 partner, 3 opponent
    finish_order: tuple[int, ...]
    unseen: tuple[Card, ...]
    known: tuple[tuple[Card, ...], ...]
    ruleset_version: int

    @classmethod
    def from_state(cls, state: GameState, player: int) -> ActionObservation:
        return cls.from_observation(ActorObservation.from_state(state, player))

    @classmethod
    def from_observation(cls, state: ActorObservation) -> ActionObservation:
        player = state.player
        context = PublicTacticalContext.from_observation(state)
        seats = tuple((player - offset) % 4 for offset in range(4))
        relative = {seat: offset for offset, seat in enumerate(seats)}
        own = player % 2
        top = context.top_player
        relation = 0 if context.top is None or top is None else 1 if top == player else 2 if top == context.partner else 3
        return cls(
            tuple(sorted(state.hand)), state.wild_card, state.level,
            tuple(state.sizes[seat] for seat in seats),
            (state.team_levels[own], state.team_levels[1 - own]),
            (state.a_failure_counts[own], state.a_failure_counts[1 - own]),
            context.top, relation, tuple(relative[seat] for seat in state.finish_order),
            context.unseen, tuple(context.known[seat] for seat in seats), state.ruleset_version,
        )


def _suited_links(cards: Counter[Card], wild: Card | None) -> int:
    # Cheap natural straight-flush structure; duplicate deck copies stay counts.
    return sum(
        min(count, cards.get(Card(card.rank + 1, card.suit), 0))
        for card, count in cards.items()
        if card != wild and card.rank < 14 and not card.is_joker
        and Card(card.rank + 1, card.suit) != wild
    )


def action_features(observation: ActionObservation, action: Pattern | None) -> tuple[float, ...]:
    """Fixed, inexpensive state-action features including contextual interactions."""
    before_cards = Counter(observation.hand)
    used_cards = Counter(action.cards if action is not None else ())
    if used_cards - before_cards:
        raise ValueError("ranking action uses unavailable cards")
    after_cards = before_cards - used_cards
    before = Counter(card.rank for card in observation.hand)
    after = Counter({rank: sum(n for card, n in after_cards.items() if card.rank == rank)
                     for rank in before})
    enemy_sizes = [observation.sizes[i] for i in (1, 3) if observation.sizes[i] > 0]
    urgency = min(enemy_sizes, default=0)
    partner_size = observation.sizes[2]
    count = len(action.cards) if action is not None else 0
    strength = comparison_rank(action, observation.level) if action is not None else 0
    def higher(card: Card) -> bool:
        return effective_rank(card.rank, observation.level) > strength
    natural_before = _suited_links(before_cards, observation.wild)
    natural_after = _suited_links(after_cards, observation.wild)
    base: tuple[float, ...] = (
        float(action is None), count / 10, strength / 18,
        float(action is not None and is_bomb_pattern(action)),
        (action.wild_used if action is not None else 0) / 2,
        float(count == len(observation.hand) and count > 0),
        sum(after_cards.values()) / 27,
        sum(n == 1 for n in after.values()) / 13,
        sum(n == 2 for n in after.values()) / 13,
        sum(n == 3 for n in after.values()) / 13,
        sum(n >= 4 for n in after.values()) / 13,
        sum(n == 2 and after[rank] == 1 for rank, n in before.items()) / 13,
        sum(n == 3 and 0 < after[rank] < 3 for rank, n in before.items()) / 13,
        sum(n >= 4 and 0 < after[rank] < 4 for rank, n in before.items()) / 13,
        sum(n == 1 and effective_rank(rank, observation.level) < 11
            for rank, n in after.items()) / 13,
        sum(n for card, n in after_cards.items()
            if effective_rank(card.rank, observation.level) > 14) / 8,
        after_cards.get(observation.wild, 0) / 2 if observation.wild is not None else 0,
        natural_after / 24, max(0, natural_before - natural_after) / 24,
        float(count > urgency > 0), float(0 < count <= partner_size),
        sum(higher(card) for card in observation.unseen) / 108 if count else 0,
        sum(higher(card) for i in (1, 3) for card in observation.known[i]) / 8 if count else 0,
        sum(higher(card) for card in observation.known[2]) / 8 if count else 0,
    )
    base += tuple(float(action is not None and action.type == kind) for kind in _TYPES)
    base += tuple(sum(n for card, n in used_cards.items() if int(card.suit) == suit) / 10
                  for suit in range(6))
    contexts = (
        float(observation.top_relation == 2), float(observation.top_relation == 3),
        float(urgency == 1), float(urgency == 2), float(urgency == 3),
        float(0 < partner_size <= 3), float(bool(observation.finish_order)),
        (observation.levels[0] - observation.levels[1]) / 12,
        float(observation.levels[0] == 14), float(observation.levels[1] == 14),
        observation.a_failures[0] / 2, observation.a_failures[1] / 2,
    )
    return base + tuple(value * context for context in contexts for value in base)


@dataclass(frozen=True)
class ActionRankerModel:
    weights: tuple[float, ...]
    sha256: str


@lru_cache(maxsize=4)
def load_model(path: str = str(MODEL_PATH)) -> ActionRankerModel:
    raw = Path(path).read_bytes()
    payload = json.loads(raw)
    if (not isinstance(payload, dict) or payload.get("schema") != MODEL_SCHEMA or payload.get("ruleset_version") != 3
            or payload.get("feature_version") != FEATURE_VERSION
            or payload.get("feature_names") != list(FEATURE_NAMES)
            or payload.get("objective") != "paired-action-ranking"):
        raise ValueError("incompatible action-ranker model")
    if not isinstance(payload.get("weights"), list):
        raise ValueError("invalid action-ranker coefficients")
    metadata = payload.get("meta")
    recipe = metadata.get("recipe") if isinstance(metadata, dict) else None
    value_sha = hashlib.sha256((MODEL_PATH.parent / "match_value.json").read_bytes()).hexdigest()
    if not isinstance(recipe, dict) or recipe.get("value_model_sha256") != value_sha:
        raise ValueError("incompatible action-ranker value model")
    weights = tuple(float(value) for value in payload["weights"])
    if len(weights) != len(FEATURE_NAMES) or not all(math.isfinite(w) for w in weights):
        raise ValueError("invalid action-ranker coefficients")
    return ActionRankerModel(weights, hashlib.sha256(raw).hexdigest())


def score_actions(
    observation: ActionObservation,
    actions: Sequence[Pattern | None],
    *,
    model: ActionRankerModel | None = None,
    deadline: float | None = None,
) -> list[float]:
    """Return relative scores only; check deadlines before and after every action."""
    check_deadline(deadline)
    if observation.ruleset_version != 3:
        raise ValueError("action ranker requires ruleset 3")
    ranker = model if model is not None else load_model()
    if len(ranker.weights) != len(FEATURE_NAMES):
        raise ValueError("invalid action-ranker dimensions")
    scores = []
    for action in actions:
        check_deadline(deadline)
        score = sum(w * x for w, x in zip(ranker.weights, action_features(observation, action)))
        if not math.isfinite(score):
            raise ValueError("non-finite action score")
        scores.append(score)
        check_deadline(deadline)
    return scores

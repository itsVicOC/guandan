"""Shared, bounded soft evidence from public passes."""
from __future__ import annotations

from dataclasses import dataclass

from ..engine.card import Card
from ..engine.events import Pass, TurnPlayed
from ..engine.hand import Pattern, PatternType, comparison_rank, effective_rank
from ..engine.state import GameState, is_teammate


@dataclass(frozen=True)
class PassEvidence:
    player: int
    top_player: int
    pattern: Pattern
    trick: int = 0
    top_remaining: int = 27


def collect_pass_evidence(state: GameState) -> tuple[PassEvidence, ...]:
    top: TurnPlayed | None = None
    passed: set[int] = set()
    finished: set[int] = set()
    trick = 0
    observations: dict[tuple, PassEvidence] = {}
    for event in state.history:
        if isinstance(event, TurnPlayed):
            top = event
            if state.ruleset_version != 1:
                passed.clear()
            if event.hand_remaining == 0:
                finished.add(event.player)
        elif isinstance(event, Pass) and top is not None:
            if not is_teammate(event.player, top.player):
                # Multiple enemy plays in one trick are correlated evidence.
                # Keep the latest family observation, not their product.
                key = (trick, event.player, top.pattern.type)
                observations[key] = PassEvidence(event.player, top.player, top.pattern, trick, top.hand_remaining)
            passed.add(event.player)
            if all(seat in finished or seat == top.player or seat in passed for seat in range(4)):
                trick += 1
                top = None
                passed.clear()
    return tuple(observations.values())[-24:]


def pass_strength(observation: PassEvidence) -> float:
    """An urgent declined single is stronger evidence than a speculative pass."""
    base = 0.80 if observation.top_remaining <= 3 else 0.94
    if observation.pattern.type == PatternType.PAIR:
        return 1.0 - (1.0 - base) * 0.45
    if observation.pattern.type in (PatternType.TRIPLE, PatternType.TRIPLE_PAIR):
        return 1.0 - (1.0 - base) * 0.25
    return base if observation.pattern.type == PatternType.SINGLE else 1.0


def card_owner_likelihood(card: Card, owner: int, evidence: tuple[PassEvidence, ...], *, level: int) -> float:
    likelihood = 1.0
    for observation in evidence:
        if observation.player != owner or is_teammate(owner, observation.top_player):
            continue
        if effective_rank(card.rank, level) > comparison_rank(observation.pattern, level):
            likelihood *= pass_strength(observation)
    return max(0.30, likelihood)


def response_evidence_multiplier(pattern: Pattern, seat: int, evidence: tuple[PassEvidence, ...], *, level: int) -> float:
    likelihood = 1.0
    for observation in evidence:
        if (
            observation.player == seat and not is_teammate(seat, observation.top_player)
            and observation.pattern.type == pattern.type
            and comparison_rank(observation.pattern, level) <= comparison_rank(pattern, level)
        ):
            likelihood *= pass_strength(observation)
    return max(0.30, likelihood)

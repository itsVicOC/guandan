"""Immutable actor-visible input shared by tactical and research components."""
from __future__ import annotations

from dataclasses import dataclass

from ..engine.card import Card
from ..engine.events import Event, ShuffleDeal
from ..engine.hand import Pattern
from ..engine.state import GameState
from ..engine.trick import current_top_player


@dataclass(frozen=True)
class ActorObservation:
    player: int
    hand: tuple[Card, ...]
    level: int
    wild_card: Card | None
    sizes: tuple[int, ...]
    team_levels: tuple[int, ...]
    a_failure_counts: tuple[int, ...]
    top_player: int | None
    table: tuple[Pattern, ...]
    passed_players: frozenset[int]
    finish_order: tuple[int, ...]
    history: tuple[Event, ...]
    ruleset_version: int

    @classmethod
    def from_state(cls, state: GameState, player: int) -> ActorObservation:
        return cls(player, tuple(state.hands[player]), state.level, state.wild_card,
                   tuple(map(len, state.hands)), tuple(state.team_levels), tuple(state.a_failure_counts),
                   current_top_player(state), tuple(state.table), frozenset(state.passed_players),
                   tuple(state.finish_order), tuple(event for event in state.history
                                                   if not isinstance(event, ShuffleDeal)), state.ruleset_version)

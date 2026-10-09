"""Optional actor-local tier-2 policy for the beginning of a root rollout.

The memo is scoped to one decision. Its key contains only that actor's cards
and sufficient public information for the frozen, default tier-2 heuristic.
No style, team-tactics or opponent-hand features are used by this policy.
"""
from __future__ import annotations

from collections import Counter

from ..engine.events import TurnPlayed
from ..engine.hand import Pattern
from ..engine.state import GameState
from ..engine.trick import current_top_player
from .tactics import select_heuristic_action

ReferenceMemo = dict[tuple, Pattern | None]


def reference_key(state: GameState, player: int) -> tuple:
    played = Counter(card.rank for event in state.history if isinstance(event, TurnPlayed)
                     for card in event.pattern.cards)
    return (player, tuple(state.hands[player]), state.level, state.wild_card,
            tuple(map(len, state.hands)), state.table[-1] if state.table else None,
            current_top_player(state), tuple(sorted(state.passed_players)),
            tuple(state.finish_order), tuple(sorted(played.items())), state.ruleset_version)


def reference_pattern(state: GameState, player: int, memo: ReferenceMemo | None) -> Pattern | None:
    if memo is None:
        return select_heuristic_action(state, player, 2)
    key = reference_key(state, player)
    if key not in memo:
        action = select_heuristic_action(state, player, 2)
        if len(memo) >= 8192:
            memo.clear()
        memo[key] = action
    return memo[key]

"""Single-observer information-set Monte Carlo tree search.

The tree stores public action histories rather than one sampled set of hidden
hands.  Every simulation samples a fresh world consistent with the root
player's information, while action statistics are shared across those worlds.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import TypeAlias

from ...engine.hand import Pattern, PatternType, comparison_rank
from ...engine.rules.comparator import is_bomb_type
from ...engine.state import GameState, IllegalPlayError, pass_turn, play_pattern, team_of
from ...engine.trick import current_top_player
from ..candidates import PatternKey, pattern_key
from ..context import opponent_min_cards
from ..valuation import enumerate_search_candidates
from .determinize import determinize
from .search import simulate_state

PassKey: TypeAlias = tuple[str]
ActionKey: TypeAlias = PatternKey | PassKey
PASS_ACTION: PassKey = ("pass",)


@dataclass(frozen=True)
class SearchStyle:
    """Search priors used to express a play style without vetoing its result."""

    bomb_willingness: float = 1.0
    teammate_awareness: float = 0.85
    control_priority: float = 0.5


@dataclass
class InformationSetNode:
    """Statistics for one public action history in the information-set tree."""

    action_key: ActionKey | None = None
    representative: Pattern | None = None
    visits: int = 0
    value_sum: float = 0.0
    availability: int = 0
    prior: float = 1.0
    children: dict[ActionKey, InformationSetNode] = field(default_factory=dict)

    @property
    def mean_value(self) -> float:
        return self.value_sum / self.visits if self.visits else 0.5


@dataclass(frozen=True)
class ActionStatistics:
    """Inspectable root statistics for tests, tuning and UI diagnostics."""

    action_key: ActionKey
    pattern: Pattern | None
    visits: int
    availability: int
    mean_value: float
    prior: float


@dataclass(frozen=True)
class SearchResult:
    """Selected action plus deterministic search diagnostics."""

    pattern: Pattern | None
    simulations: int
    sampled_worlds: int
    elapsed_seconds: float
    actions: tuple[ActionStatistics, ...]


def _legal_action_map(
    state: GameState,
    player: int,
    *,
    max_actions: int,
) -> dict[ActionKey, Pattern | None]:
    actions: dict[ActionKey, Pattern | None] = {}
    for pattern in enumerate_search_candidates(
        state,
        player,
        max_candidates=max_actions,
    ):
        actions.setdefault(pattern_key(pattern), pattern)
    if state.table:
        actions[PASS_ACTION] = None
    return actions


def _action_prior(
    state: GameState,
    player: int,
    pattern: Pattern | None,
    style: SearchStyle,
) -> float:
    if pattern is None:
        top_player = current_top_player(state)
        if top_player is not None and team_of(top_player) == team_of(player):
            return 1.0 + 2.0 * style.teammate_awareness
        if 0 < opponent_min_cards(state, player) <= 3:
            return 0.08
        return 0.35

    hand_size = max(1, state.hand_size(player))
    if len(pattern.cards) == hand_size:
        return 12.0

    # Candidate generation already performed the expensive structure ranking.
    # Priors intentionally use only O(cards) features because they are queried
    # at every visited node and must not dominate the simulation budget.
    cost = float(pattern.weight + pattern.wild_used * 5)
    if pattern.type in (
        PatternType.STRAIGHT,
        PatternType.PAIR_SEQUENCE,
        PatternType.TRIPLE_SEQUENCE,
        PatternType.TRIPLE_PAIR,
    ):
        cost -= len(pattern.cards) * 0.7
    prior = math.exp(-max(-12.0, min(36.0, cost)) / 12.0)
    prior *= 1.0 + len(pattern.cards) / hand_size

    if is_bomb_type(pattern.type):
        urgency = opponent_min_cards(state, player)
        urgent_multiplier = 3.0 if 0 < urgency <= 3 else 1.0
        prior *= max(0.05, style.bomb_willingness) * urgent_multiplier
    elif pattern.type in (
        PatternType.STRAIGHT,
        PatternType.PAIR_SEQUENCE,
        PatternType.TRIPLE_SEQUENCE,
        PatternType.TRIPLE_PAIR,
    ):
        prior *= 1.15

    if state.table and style.control_priority > 0:
        prior *= 1.0 + style.control_priority * min(
            0.35,
            comparison_rank(pattern, state.level) / 400.0,
        )
    return max(0.01, prior)


def _apply_action(
    state: GameState,
    player: int,
    pattern: Pattern | None,
) -> bool:
    try:
        if pattern is None:
            pass_turn(state, player)
        else:
            play_pattern(state, player, pattern)
    except IllegalPlayError:
        return False
    return True


def team_selection_score(
    child: InformationSetNode,
    *,
    node_visits: int,
    actor_team: int,
    root_team: int,
    exploration: float,
    prior_weight: float,
) -> float:
    """PUCT-like score where opponents minimize the root team's value."""
    if child.visits == 0:
        return float("inf")
    root_value = child.mean_value
    exploitation = root_value if actor_team == root_team else 1.0 - root_value
    available = max(2, child.availability)
    explore = exploration * math.sqrt(math.log(available) / child.visits)
    prior_bonus = (
        prior_weight
        * child.prior
        * math.sqrt(max(1, node_visits))
        / (child.visits + 1)
    )
    return exploitation + explore + prior_bonus


def _select_existing_child(
    node: InformationSetNode,
    actions: dict[ActionKey, Pattern | None],
    *,
    actor_team: int,
    root_team: int,
    exploration: float,
    prior_weight: float,
) -> tuple[InformationSetNode, Pattern | None] | None:
    available: list[tuple[ActionKey, InformationSetNode]] = []
    for key, child in node.children.items():
        if key in actions:
            available.append((key, child))
    if not available:
        return None
    key, child = max(
        available,
        key=lambda item: team_selection_score(
            item[1],
            node_visits=node.visits,
            actor_team=actor_team,
            root_team=root_team,
            exploration=exploration,
            prior_weight=prior_weight,
        ),
    )
    return child, actions[key]


def _expand_action(
    node: InformationSetNode,
    state: GameState,
    player: int,
    actions: dict[ActionKey, Pattern | None],
    style: SearchStyle,
) -> tuple[InformationSetNode, Pattern | None] | None:
    unexpanded = [
        (key, pattern)
        for key, pattern in actions.items()
        if key not in node.children
    ]
    if not unexpanded:
        return None
    key, pattern = max(
        unexpanded,
        key=lambda item: _action_prior(state, player, item[1], style),
    )
    child = InformationSetNode(
        action_key=key,
        representative=pattern,
        availability=1,
        prior=_action_prior(state, player, pattern, style),
    )
    node.children[key] = child
    return child, pattern


def _has_expansion_capacity(
    node: InformationSetNode,
    actions: dict[ActionKey, Pattern | None],
    widening_limit: int,
) -> bool:
    """Return whether this sampled world can expose another legal child."""
    available_children = sum(key in actions for key in node.children)
    return available_children < min(len(actions), widening_limit)


def information_set_search(
    state: GameState,
    player: int,
    *,
    rng: random.Random,
    iterations: int = 60,
    time_budget_ms: int = 0,
    max_actions: int = 10,
    max_tree_depth: int = 12,
    rollout_strategy: int = 2,
    rollout_max_turns: int = 40,
    exploration: float = 1.20,
    prior_weight: float = 0.18,
    widening_c: float = 1.8,
    widening_alpha: float = 0.5,
    style: SearchStyle | None = None,
) -> SearchResult:
    """Search one public information set using a fresh world per simulation."""
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if max_actions <= 0:
        raise ValueError("max_actions must be positive")
    if max_tree_depth <= 0 or rollout_max_turns <= 0:
        raise ValueError("search depth and rollout limit must be positive")

    search_style = style or SearchStyle()
    root = InformationSetNode(availability=iterations)
    root_team = team_of(player)
    root_actions = _legal_action_map(state, player, max_actions=max_actions)
    started = time.perf_counter()
    deadline = started + time_budget_ms / 1000.0 if time_budget_ms > 0 else None
    simulations = 0

    while simulations < iterations:
        if simulations > 0 and deadline is not None and time.perf_counter() >= deadline:
            break
        sampled_state = determinize(state, player, rng)
        node = root
        path = [root]

        for _depth in range(max_tree_depth):
            if sampled_state.finished:
                break
            actor = sampled_state.current_player()
            actions = (
                root_actions
                if node is root
                else _legal_action_map(
                    sampled_state,
                    actor,
                    max_actions=max_actions,
                )
            )
            if not actions:
                break

            # Availability is an information-set statistic: every existing
            # child that is legal in this sampled world gets credit, including
            # iterations that go on to expand a different action.
            for key, child in node.children.items():
                if key in actions:
                    child.availability += 1

            widening_limit = max(
                1,
                math.ceil(widening_c * (node.visits + 1) ** widening_alpha),
            )
            actor_style = search_style if team_of(actor) == root_team else SearchStyle()
            chosen: tuple[InformationSetNode, Pattern | None] | None = None
            # Hidden hands can make children from earlier worlds unavailable.
            # Progressive widening therefore counts only children legal in the
            # current world; otherwise the simulation can stop despite having
            # an unexpanded legal action.
            if _has_expansion_capacity(node, actions, widening_limit):
                chosen = _expand_action(node, sampled_state, actor, actions, actor_style)
            if chosen is None:
                chosen = _select_existing_child(
                    node,
                    actions,
                    actor_team=team_of(actor),
                    root_team=root_team,
                    exploration=exploration,
                    prior_weight=prior_weight,
                )
            if chosen is None:
                break
            child, pattern = chosen
            if not _apply_action(sampled_state, actor, pattern):
                break
            node = child
            path.append(node)
            if node.visits == 0:
                break

        value = simulate_state(
            sampled_state,
            player,
            rollout_strategy_level=rollout_strategy,
            max_turns=rollout_max_turns,
            copy_state=False,
        )
        for visited in path:
            visited.visits += 1
            visited.value_sum += value
        simulations += 1

    action_stats = tuple(
        ActionStatistics(
            action_key=key,
            pattern=root_actions.get(key, child.representative),
            visits=child.visits,
            availability=child.availability,
            mean_value=child.mean_value,
            prior=child.prior,
        )
        for key, child in root.children.items()
        if key in root_actions
    )
    best = max(action_stats, key=lambda item: (item.visits, item.mean_value), default=None)
    return SearchResult(
        pattern=best.pattern if best is not None else None,
        simulations=simulations,
        sampled_worlds=simulations if simulations else 0,
        elapsed_seconds=time.perf_counter() - started,
        actions=action_stats,
    )

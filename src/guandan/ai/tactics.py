"""Fast public-information tactics shared by the first three difficulty levels."""
from __future__ import annotations

from ..engine.card import RANK_BIG_JOKER, RANK_SMALL_JOKER
from ..engine.hand import Pattern, PatternType, comparison_rank, effective_rank
from ..engine.rules.comparator import is_bomb_type
from ..engine.state import GameState, is_teammate
from ..engine.trick import current_top_player
from .candidates import enumerate_legal_patterns, pattern_key
from .context import opponent_min_cards
from .hand_plan import estimate_remaining_plays, remaining_cards
from .memory import PlayedTracker
from .valuation import estimate_pattern_cost


def _shortlist(state: GameState, player: int, limit: int) -> list[Pattern]:
    legal = enumerate_legal_patterns(state, player)
    if len(legal) <= limit:
        return legal
    ranked = sorted(legal, key=lambda p: estimate_pattern_cost(state, player, p))
    chosen: dict[tuple, Pattern] = {}

    def keep(pattern: Pattern | None) -> None:
        if pattern is not None and len(chosen) < limit:
            chosen.setdefault(pattern_key(pattern), pattern)

    hand_size = state.hand_size(player)
    keep(next((p for p in ranked if len(p.cards) == hand_size), None))
    keep(ranked[0])
    keep(max(legal, key=lambda p: (len(p.cards), -p.wild_used)))
    normal = [p for p in legal if not is_bomb_type(p.type)]
    if normal:
        keep(max(normal, key=lambda p: (len(p.cards), comparison_rank(p, state.level))))
        keep(max(normal, key=lambda p: comparison_rank(p, state.level)))
    bombs = [p for p in legal if is_bomb_type(p.type)]
    if bombs:
        keep(min(bombs, key=lambda p: (p.length, comparison_rank(p, state.level))))
    for kind in PatternType:
        keep(next((p for p in ranked if p.type == kind), None))
    for pattern in ranked:
        keep(pattern)
        if len(chosen) >= limit:
            break
    return list(chosen.values())


def _control_bonus(
    state: GameState, player: int, pattern: Pattern, tracker: PlayedTracker
) -> float:
    if pattern.type not in (PatternType.SINGLE, PatternType.PAIR, PatternType.TRIPLE):
        return 0.0
    target = comparison_rank(pattern, state.level)
    needed = len(pattern.cards)
    own = state.hands[player]
    for rank in (*range(2, 15), RANK_SMALL_JOKER, RANK_BIG_JOKER):
        effective = effective_rank(rank, state.level)
        if effective > target and tracker.in_someone_hand(rank, own) >= needed:
            return 0.0
    return 1.4


def _pattern_score(
    state: GameState,
    player: int,
    pattern: Pattern,
    *,
    tier: int,
    tracker: PlayedTracker | None,
) -> float:
    remaining = remaining_cards(state.hands[player], pattern.cards)
    width = 6 if tier == 1 else 24
    score = 3.0 * estimate_remaining_plays(remaining, state.wild_card, state.level, width=width)
    score += 0.13 * estimate_pattern_cost(state, player, pattern)
    urgency = opponent_min_cards(state, player)
    if is_bomb_type(pattern.type):
        score += 3.5 if urgency > 5 else 1.2 if urgency > 2 else 0.0
    if pattern.wild_used and len(remaining) > 0:
        score += pattern.wild_used * 0.4
    if tracker is not None:
        control = _control_bonus(state, player, pattern, tracker)
        score += control if urgency > 3 else -control
    if not state.table:
        score -= 0.36 * (len(pattern.cards) - 1)
    if not remaining:
        score -= 8.0
    return score


def select_heuristic_action(state: GameState, player: int, tier: int) -> Pattern | None:
    """Select a legal play or intentional pass without hidden-hand access."""
    if tier not in (0, 1, 2):
        raise ValueError("heuristic tier must be 0, 1, or 2")
    if tier == 0:
        candidates = _shortlist(state, player, 12)
        if not candidates:
            return None
        finish = next((p for p in candidates if len(p.cards) == state.hand_size(player)), None)
        if finish is not None:
            return finish
        if state.table:
            top = current_top_player(state)
            danger = opponent_min_cards(state, player)
            if top is not None and is_teammate(top, player) and danger > 1:
                return None
            normal = [p for p in candidates if not is_bomb_type(p.type)]
            if normal:
                return min(normal, key=lambda p: estimate_pattern_cost(state, player, p))
            if danger > 5:
                return None
        return min(candidates, key=lambda p: estimate_pattern_cost(state, player, p))

    candidates = _shortlist(state, player, 12 if tier == 1 else 28)
    if not candidates:
        return None
    tracker = PlayedTracker.from_history(state) if tier == 2 else None
    scored = [
        (_pattern_score(state, player, p, tier=tier, tracker=tracker), p)
        for p in candidates
    ]
    best_score, best = min(scored, key=lambda item: item[0])
    if not state.table:
        return best
    current_plan = estimate_remaining_plays(
        state.hands[player], state.wild_card, state.level, width=6 if tier == 1 else 24
    )
    pass_score = 3.0 * current_plan
    top = current_top_player(state)
    urgency = opponent_min_cards(state, player)
    if top is not None and is_teammate(top, player):
        teammate_cards = state.hand_size(top)
        if (
            tier == 2
            and urgency > 3
            and teammate_cards >= state.hand_size(player) + 5
            and not is_bomb_type(best.type)
            and len(best.cards) >= 4
            and len(remaining_cards(state.hands[player], best.cards)) <= 3
        ):
            return best
        pass_score -= 5.0 if teammate_cards <= 3 and urgency > 1 else 3.3
        if urgency == 1 and state.table[-1].type == PatternType.SINGLE:
            pass_score += 6.0
    elif urgency == 1:
        pass_score += 9.0
    elif 0 < urgency <= 3:
        pass_score += 5.0
    elif 0 < urgency <= 5:
        pass_score += 2.0
    # Passing is a legitimate alternative.  A good multi-card shed or an
    # urgent block can outweigh it; expensive speculative bombs usually do not.
    return best if best_score < pass_score else None

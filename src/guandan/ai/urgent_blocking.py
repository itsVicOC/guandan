"""Actor-public, short-hand exit risks for optional root tactics.

The hypergeometric distribution is exact under a uniform public-card pool.
Public pass evidence remains a soft heuristic. The maximum of seat risks is
deliberately not advertised as a joint exit probability or a solved game value.
"""
from __future__ import annotations

import math
import time
from collections import Counter
from itertools import combinations_with_replacement

from ..engine.card import Card, Suit
from ..engine.hand import Pattern
from ..engine.rules.patterns import find_complete_pattern
from ..engine.state import GameState, clone_state_for_search, pass_turn, play_pattern
from ..engine.trick import current_top_player
from .belief import response_evidence_multiplier
from .candidates import pattern_key
from .context import PublicTacticalContext, opponent_min_cards
from .memory import PlayedTracker
from .tactics import _pass_score, _pattern_score, _shortlist


class BlockingTimeout(TimeoutError):
    """Discard the entire tactical proposal on timeout."""


def _check(deadline: float | None) -> None:
    if deadline is not None and time.perf_counter() >= deadline:
        raise BlockingTimeout("short-hand tactical deadline exceeded")


def action_key(action: Pattern | None) -> tuple:
    return ("pass",) if action is None else pattern_key(action)


def _category(card: Card, wild: Card | None) -> Card:
    # Suits cannot change any <=3-card pattern except the wildcard identity.
    if card == wild or card.is_joker:
        return card
    return Card(card.rank, Suit.CLUBS if wild is None or wild.suit != Suit.CLUBS else Suit.DIAMONDS)


class ShortHandRisks:
    """One decision's disjoint complete-hand outcomes, including public cards."""

    def __init__(self, context: PublicTacticalContext, *, deadline: float | None = None):
        self.context = context
        self.deadline = deadline
        known = Counter(card for cards in context.known for card in cards)
        pool = Counter(context.unseen)
        if known - pool or any(len(context.known[s]) > context.sizes[s] for s in range(4)):
            raise ValueError("inconsistent public known-card accounting")
        pool.subtract(known)
        if any(n < 0 for n in pool.values()):
            raise ValueError("inconsistent public unknown-card accounting")
        pool_counts = Counter[Card]()
        for card, count in pool.items():
            pool_counts[_category(card, context.wild)] += count
        self.outcomes: dict[int, tuple[tuple[Pattern, float], ...]] = {}
        for seat in range(4):
            if seat % 2 == context.player % 2 or not 1 <= context.sizes[seat] <= 3:
                continue
            _check(deadline)
            fixed = tuple(_category(c, context.wild) for c in context.known[seat])
            needed = context.sizes[seat] - len(fixed)
            total = sum(pool_counts.values())
            if needed > total:
                raise ValueError("insufficient public pool for short hand")
            denominator = math.comb(total, needed)
            outcomes = []
            categories = sorted(card for card, n in pool_counts.items() if n > 0)
            for draw in combinations_with_replacement(categories, needed):
                _check(deadline)
                counts = Counter(draw)
                if any(n > pool_counts[card] for card, n in counts.items()):
                    continue
                mass = math.prod(math.comb(pool_counts[card], n) for card, n in counts.items())
                pattern = find_complete_pattern((*fixed, *draw), context.wild)
                if pattern is not None:
                    outcomes.append((pattern, mass / denominator))
            self.outcomes[seat] = tuple(outcomes)
        self._cache: dict[tuple[int, Pattern | None], float] = {}

    def probability(self, seat: int, top: Pattern | None) -> float:
        """Legal full-hand exit on ``top``; None means an unrestricted lead."""
        _check(self.deadline)
        key = (seat, top)
        if key not in self._cache:
            risk = sum(mass for pattern, mass in self.outcomes.get(seat, ())
                       if top is None or pattern.can_be_played_on(top, level=self.context.level))
            if top is not None and len(self.context.known[seat]) < self.context.sizes[seat]:
                risk *= response_evidence_multiplier(
                    top, seat, self.context.pass_evidence, level=self.context.level,
                )
            self._cache[key] = min(1.0, max(0.0, risk))
        return self._cache[key]

    def after_action(self, state: GameState, player: int, action: Pattern | None) -> dict[int, float]:
        """Project only the root action through the engine, stripping hidden cards.

        All eligible opponents on the current top count, even after a partner's
        opportunity to respond. A pass closing the trick checks the actual new
        leader, including jiefeng. No future partner response is presumed.
        """
        _check(self.deadline)
        sim = clone_state_for_search(state)
        for seat in range(4):
            if seat != player:
                sim.hands[seat] = [Card(2, Suit.DIAMONDS)] * state.hand_size(seat)
        if action is None:
            pass_turn(sim, player)
        else:
            play_pattern(sim, player, action)
        if sim.finished:
            return {}
        if not sim.table:
            leader = sim.current_player()
            return {leader: self.probability(leader, None)} if leader in self.outcomes else {}
        top = current_top_player(sim)
        threats = {}
        for offset in range(1, 5):
            seat = (player - offset) % 4
            if seat == top:
                break
            if seat in self.outcomes and seat not in sim.passed_players and seat not in sim.finish_order:
                threats[seat] = self.probability(seat, sim.table[-1])
        return threats


def blocking_reference(
    state: GameState, player: int, baseline: Pattern | None, *,
    weight: float, deadline: float | None,
) -> tuple[Pattern | None, dict]:
    """Return a complete proposal or the original reference, without RNG draws."""
    started = time.perf_counter()
    report: dict = {"original_key": action_key(baseline), "reference_key": action_key(baseline),
                    "weight": weight, "triggered": False, "reason": "no_short_opponent",
                    "risks": [], "candidate_replaced": False}
    selected = baseline
    try:
        _check(deadline)
        if not 1 <= opponent_min_cards(state, player) <= 3:
            return baseline, report
        report["triggered"] = True
        context = PublicTacticalContext.from_state(state, player)
        # Complete production accounting is required; partial hand-made states
        # retain the baseline instead of creating a misleading distribution.
        if len(context.unseen) != sum(context.sizes[s] for s in range(4) if s != player):
            raise ValueError("incomplete public deck accounting")
        risks = ShortHandRisks(context, deadline=deadline)
        candidates = _shortlist(state, player, 28)
        finish = next((p for p in candidates if len(p.cards) == state.hand_size(player)), None)
        if finish is not None:
            selected = finish
            report["reason"] = "legal_finish"
        else:
            tracker = PlayedTracker.from_history(state)
            scores: list[tuple[float, Pattern | None]] = [
                (_pattern_score(state, player, p, tier=2, tracker=tracker), p) for p in candidates
            ]
            _check(deadline)
            if state.table:
                # Preserve the old policy's pass-on-equal-score convention.
                scores.insert(0, (_pass_score(state, player, tier=2), None))
            if not scores:
                return baseline, report
            ranked = []
            for base_score, action in scores:
                per_seat = risks.after_action(state, player, action)
                penalty = weight * max(per_seat.values(), default=0.0)
                ranked.append((base_score + penalty, action))
                report["risks"].append({"key": action_key(action), "base_score": base_score,
                                        "score": base_score + penalty, "by_seat": per_seat})
            selected = min(ranked, key=lambda item: item[0])[1]
            report["reason"] = "changed" if action_key(selected) != action_key(baseline) else "unchanged"
        _check(deadline)
        report["reference_key"] = action_key(selected)
        return selected, report
    except BlockingTimeout:
        report.update(reason="budget_limited", risks=[])
        return baseline, report
    except ValueError:
        report.update(reason="incomplete_public_state", risks=[])
        return baseline, report
    finally:
        report["elapsed_seconds"] = time.perf_counter() - started

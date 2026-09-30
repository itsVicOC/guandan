"""Bounded public-world evaluation of leads and subsequent recovery."""
from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass
from typing import Sequence

from ..engine.events import TurnPlayed
from ..engine.hand import Pattern
from ..engine.state import GameState, clone_state_for_search, is_teammate, pass_turn, play_pattern
from ..engine.trick import current_top_player
from .candidates import enumerate_legal_patterns, pattern_key
from .context import opponent_min_cards
from .mcts.determinize import determinize
from .valuation import estimate_pattern_cost


@dataclass(frozen=True)
class LeadChainStatistics:
    samples: int
    opponent_exit: float
    partner_exit: float
    own_recovery: float
    opponent_control: float

    @property
    def adjustment(self) -> float:
        return 12.0 * self.opponent_exit - 3.0 * self.partner_exit + 1.2 * self.opponent_control - 1.8 * self.own_recovery


def actor_response(state: GameState, player: int) -> Pattern | None:
    """A legal actor-local proxy; no other hand content is inspected."""
    legal = enumerate_legal_patterns(state, player)
    finish = next((p for p in legal if len(p.cards) == state.hand_size(player)), None)
    if finish is not None:
        return finish
    top = current_top_player(state)
    if state.table and top is not None and is_teammate(top, player) and opponent_min_cards(state, player) > 1:
        return None
    return min(legal, key=lambda p: estimate_pattern_cost(state, player, p)) if legal else None


def evaluate_leads(
    state: GameState, player: int, patterns: Sequence[Pattern], *,
    worlds: int = 4, deadline: float | None = None,
) -> dict[tuple, LeadChainStatistics]:
    """All leads share completed worlds and a four-action response horizon."""
    if state.table or player != state.current_player() or not patterns:
        return {}
    # Own cards and visible plays determine reproducibility. Neither the
    # private shuffle seed nor actual hidden cards enter the sampler seed.
    public = (tuple(sorted(state.hands[player])), tuple(state.hand_size(s) for s in range(4)),
              tuple((e.player, e.pattern) for e in state.history if isinstance(e, TurnPlayed)))
    seed = int.from_bytes(hashlib.sha256(repr(public).encode()).digest()[:8], "big")
    rng = random.Random(seed)
    totals = [[0.0] * 4 for _ in patterns]
    completed = 0
    for _ in range(worlds):
        if deadline is not None and time.perf_counter() >= deadline:
            break
        try:
            world = determinize(state, player, rng)
        except ValueError:
            return {}
        values = []
        for pattern in patterns:
            if deadline is not None and time.perf_counter() >= deadline:
                return _reports(patterns, totals, completed)
            sim = clone_state_for_search(world)
            play_pattern(sim, player, pattern)
            before = set(sim.finish_order)
            for _step in range(4):
                if deadline is not None and time.perf_counter() >= deadline:
                    return _reports(patterns, totals, completed)
                if sim.finished or sim.current_player() == player:
                    break
                seat = sim.current_player()
                response = actor_response(sim, seat)
                if response is None:
                    pass_turn(sim, seat)
                else:
                    play_pattern(sim, seat, response)
            new_finishers = set(sim.finish_order) - before
            enemy_exit = any(not is_teammate(seat, player) for seat in new_finishers)
            partner_exit = (player + 2) % 4 in new_finishers
            top = current_top_player(sim)
            enemy_control = top is not None and not is_teammate(top, player)
            recover = not enemy_control or bool(enumerate_legal_patterns(sim, player))
            values.append((float(enemy_exit), float(partner_exit), float(recover and not enemy_exit), float(enemy_control)))
        for index, row in enumerate(values):
            for column, value in enumerate(row):
                totals[index][column] += value
        completed += 1
    return _reports(patterns, totals, completed)


def _reports(patterns, totals, completed):
    # A partial round is discarded. Sparse evidence leaves the lightweight
    # tactical score intact, rather than manufacturing a certain response.
    if completed < 3:
        return {}
    return {pattern_key(p): LeadChainStatistics(completed, *(v / completed for v in row)) for p, row in zip(patterns, totals)}

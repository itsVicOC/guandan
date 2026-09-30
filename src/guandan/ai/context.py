"""AI decision context helpers."""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from math import comb

from ..engine.card import Card
from ..engine.deck import make_deck
from ..engine.events import Pass, TributeReturned, TributeSent, TurnPlayed
from ..engine.hand import Pattern, PatternType, comparison_rank, effective_rank
from ..engine.rules.comparator import is_bomb_type
from ..engine.rules.patterns import detect_patterns, find_complete_pattern
from ..engine.state import (
    CURRENT_RULESET_VERSION,
    LEGACY_RULESET_VERSION,
    GameState,
    is_teammate,
    partner_of,
)
from ..engine.trick import current_top_player
from .belief import PassEvidence, collect_pass_evidence, response_evidence_multiplier

_FULL_DECK = tuple(make_deck())


def opponent_hand_sizes(state: GameState, player: int) -> list[int]:
    """Active opponents' hand sizes, excluding finished players."""
    return [
        state.hand_size(p)
        for p in range(4)
        if not is_teammate(p, player) and state.hand_size(p) > 0
    ]


def opponent_min_cards(state: GameState, player: int) -> int:
    """Minimum active opponent hand size; 0 when no opponent is active."""
    return min(opponent_hand_sizes(state, player), default=0)


def opponent_has_one_card(state: GameState, player: int) -> bool:
    """Whether any active opponent is down to one card."""
    return opponent_min_cards(state, player) == 1


@lru_cache(maxsize=8192)
def _holding_chance(total: int, available: int, capacity: int, needed: int) -> float:
    """Hypergeometric marginal; no private hand is needed to estimate it."""
    if needed <= 0:
        return 1.0
    if capacity < needed or available < needed or total <= 0:
        return 0.0
    capacity = min(capacity, total)
    denominator = comb(total, capacity)
    return sum(
        comb(available, count) * comb(total - available, capacity - count)
        for count in range(needed, min(available, capacity) + 1)
        if 0 <= capacity - count <= total - available
    ) / denominator


@dataclass(frozen=True)
class PublicTacticalContext:
    """One actor's observable information, also safe inside sampled continuations.

    Response estimates are deliberately soft marginals, not an assertion about
    any particular hidden hand. Only publicly revealed tribute cards have an
    owner. The shuffled deal's seed and all other hands' contents are ignored.
    """

    player: int
    partner: int
    level: int
    sizes: tuple[int, ...]
    order: tuple[int, ...]
    top_player: int | None
    top: Pattern | None
    unseen: tuple[Card, ...]
    known: tuple[tuple[Card, ...], ...]
    leads: tuple[tuple[int, Pattern], ...]
    passes: tuple[tuple[int, int, Pattern], ...]
    wild: Card | None
    ruleset_version: int = CURRENT_RULESET_VERSION
    own_hand: tuple[Card, ...] = ()
    pass_evidence: tuple[PassEvidence, ...] = ()
    _risks: dict[tuple[Pattern, int, bool], float] = field(default_factory=dict, compare=False, repr=False)
    _unknown_counts: Counter[int] = field(init=False, compare=False, repr=False)
    _known_counts: tuple[Counter[int], ...] = field(init=False, compare=False, repr=False)
    _unknown_total: int = field(init=False, compare=False, repr=False)
    _unknown_wilds: int = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        # Response comparisons reuse the same public pool; do this once per
        # acting seat rather than rebuilding it for every candidate/owner.
        known_counts = tuple(Counter(card.rank for card in cards) for cards in self.known)
        counts = Counter(card.rank for card in self.unseen)
        for known in known_counts:
            counts.subtract(known)
        object.__setattr__(self, "_known_counts", known_counts)
        object.__setattr__(self, "_unknown_counts", +counts)
        object.__setattr__(self, "_unknown_total", len(self.unseen) - sum(map(len, self.known)))
        object.__setattr__(self, "_unknown_wilds", (
            sum(card == self.wild for card in self.unseen)
            - sum(card == self.wild for cards in self.known for card in cards)
        ) if self.wild else 0)

    @classmethod
    def from_state(cls, state: GameState, player: int) -> PublicTacticalContext:
        unseen = Counter(_FULL_DECK)
        unseen.subtract(state.hands[player])
        known: list[list[Card]] = [[], [], [], []]
        leads: list[tuple[int, Pattern]] = []
        passes: list[tuple[int, int, Pattern]] = []
        top: tuple[int, Pattern] | None = None
        passed: set[int] = set()
        finished: set[int] = set()
        new_trick = True
        for event in state.history:
            if isinstance(event, TurnPlayed):
                unseen.subtract(event.pattern.cards)
                for card in event.pattern.cards:
                    if card in known[event.player]:
                        known[event.player].remove(card)
                if new_trick:
                    leads.append((event.player, event.pattern))
                new_trick = False
                top = (event.player, event.pattern)
                if state.ruleset_version != 1:
                    passed.clear()
                if event.hand_remaining == 0:
                    finished.add(event.player)
            elif isinstance(event, Pass) and top is not None:
                passes.append((event.player, top[0], top[1]))
                passed.add(event.player)
                new_trick = all(
                    seat in finished or seat == top[0] or seat in passed
                    for seat in range(4)
                )
                if new_trick:
                    passed.clear()
            elif isinstance(event, (TributeSent, TributeReturned)):
                if event.card in known[event.from_player]:
                    known[event.from_player].remove(event.card)
                known[event.to_player].append(event.card)
        sizes = tuple(state.hand_size(seat) for seat in range(4))
        known[player] = []  # Already removed from the unseen pool with our hand.
        known = [cards[:sizes[seat]] for seat, cards in enumerate(known)]
        order = tuple(
            seat for offset in range(1, 4)
            if sizes[seat := (player - offset) % 4] > 0
            and (not state.table or seat not in state.passed_players)
        )
        return cls(
            player, partner_of(player), state.level, sizes, order,
            current_top_player(state), state.table[-1] if state.table else None,
            tuple(sorted(unseen.elements())), tuple(tuple(cards) for cards in known),
            tuple(leads[-8:]), tuple(passes[-12:]), state.wild_card, state.ruleset_version,
            tuple(state.hands[player]), collect_pass_evidence(state),
        )

    @property
    def opponents(self) -> tuple[int, ...]:
        # ``order`` describes passing on the current top. A proposed play
        # resets those locks in current rules; all active opponents reenter.
        if self.ruleset_version == LEGACY_RULESET_VERSION:
            return tuple(seat for seat in self.order if not is_teammate(seat, self.player))
        return tuple(
            seat for offset in range(1, 4)
            if self.sizes[seat := (self.player - offset) % 4] > 0
            and not is_teammate(seat, self.player)
        )

    @property
    def current_opponent_min_cards(self) -> int:
        """Immediate threats if we pass, before any new play resets locks."""
        return min((self.sizes[seat] for seat in self.order if not is_teammate(seat, self.player)), default=0)

    def response_risk(self, pattern: Pattern, seat: int, *, finish_only: bool = False) -> float:
        key = (pattern, seat, finish_only)
        if key not in self._risks:
            self._risks[key] = self._response_risk(pattern, seat, finish_only=finish_only)
        return self._risks[key]

    def _response_risk(self, pattern: Pattern, seat: int, *, finish_only: bool) -> float:
        """Estimate a legal response, including bombs and public known cards."""
        size = self.sizes[seat]
        if size <= 0:
            return 0.0
        known = self.known[seat]
        if len(known) == size:
            return float(any(
                p.can_be_played_on(pattern, level=self.level)
                and (not finish_only or len(p.cards) == size)
                for p in detect_patterns(known, self.wild)
            ))
        counts = self._unknown_counts
        own_known = self._known_counts[seat]
        total = self._unknown_total
        capacity = size - len(known)
        wilds = self._unknown_wilds
        known_wilds = sum(card == self.wild for card in known) if self.wild else 0

        def group(rank: int, needed: int, allow_wild: bool = True) -> float:
            # A wildcard's own rank must not be counted twice. Wild support
            # is a soft upper estimate and is never available for joker groups.
            available = counts[rank]
            if allow_wild and rank <= 14 and self.wild and rank != self.wild.rank:
                available += wilds
            supported = known_wilds if allow_wild and rank <= 14 and self.wild and rank != self.wild.rank else 0
            return _holding_chance(
                max(0, total), min(max(0, total), available), capacity,
                max(0, needed - own_known[rank] - supported),
            )

        risk = 0.0
        target = comparison_rank(pattern, self.level)
        if pattern.type in (PatternType.SINGLE, PatternType.PAIR, PatternType.TRIPLE, PatternType.TRIPLE_PAIR):
            needed = 1 if pattern.type == PatternType.SINGLE else 2 if pattern.type == PatternType.PAIR else 3
            if size >= len(pattern.cards) and (not finish_only or size == len(pattern.cards)):
                if needed == 1:
                    higher = sum(count for rank, count in counts.items() if effective_rank(rank, self.level) > target)
                    revealed = any(effective_rank(card.rank, self.level) > target for card in known)
                    risk = 1.0 if revealed else _holding_chance(max(0, total), higher, capacity, 1)
                else:
                    risk = min(1.0, sum(
                        group(rank, needed)
                        for rank in counts.keys() | own_known.keys()
                        if effective_rank(rank, self.level) > target
                        and (needed < 3 or rank <= 14)
                    ))
                    if pattern.type == PatternType.TRIPLE_PAIR:
                        risk *= 0.55
        elif not is_bomb_type(pattern.type) and size >= len(pattern.cards) and (not finish_only or size == len(pattern.cards)):
            length, needed = {
                PatternType.STRAIGHT: (5, 1),
                PatternType.PAIR_SEQUENCE: (3, 2),
                PatternType.TRIPLE_SEQUENCE: (2, 3),
            }.get(pattern.type, (0, 0))
            for end in range(2 + length - 1, 15):
                if end <= target:
                    continue
                chance = 1.0
                for rank in range(end - length + 1, end + 1):
                    chance *= group(rank, needed)
                risk += chance
            risk = min(1.0, risk)
        if pattern.type != PatternType.FOUR_JOKERS and size >= 4:
            def bomb_needed(rank: int) -> int:
                if pattern.type == PatternType.STRAIGHT_FLUSH:
                    return 6
                if pattern.type == PatternType.BOMB:
                    return pattern.length if effective_rank(rank, self.level) > target else pattern.length + 1
                return 4

            bomb_risk = min(1.0, sum(
                group(rank, size if finish_only else bomb_needed(rank))
                for rank in range(2, 15) if size >= bomb_needed(rank)
            ))
            # Four jokers can always answer, but must actually fit in the hand.
            if not finish_only or size == 4:
                bomb_risk = max(bomb_risk, group(100, 2, False) * group(101, 2, False))
            risk = max(risk, bomb_risk)
        # Past passes on enemy-controlled tricks are weak evidence. A pass on
        # a partner's play says little about what could have been played.
        risk *= response_evidence_multiplier(pattern, seat, self.pass_evidence, level=self.level)
        return max(0.0, min(1.0, risk))

    def finish_risk(self, pattern: Pattern) -> float:
        """Risk of an opponent finishing immediately on this particular play."""
        return max((
            self.response_risk(pattern, seat, finish_only=True)
            for seat in self.opponents
        ), default=0.0)

    def lead_adjustment(self, pattern: Pattern) -> float:
        """Lower is preferable: block exits, pass the lead, retain a way back."""
        risk = self.finish_risk(pattern)
        opponent_response = max((self.response_risk(pattern, seat) for seat in self.opponents), default=0.0)
        partner_response = self.response_risk(pattern, self.partner) if self.sizes[self.partner] else 0.0
        support = 1.8 if 0 < self.sizes[self.partner] <= 3 else 0.35
        score = 12.0 * risk + 1.2 * opponent_response - support * partner_response
        # Retain an actual response in our residual hand. A high card being
        # spent in the lead cannot also be counted as a later recovery card.
        if self.own_hand:
            rest = Counter(self.own_hand)
            rest.subtract(pattern.cards)
            # Keep rollout recovery linear in hand size; root joint worlds
            # handle sequences, flushes and alternative wildcard material.
            by_rank: dict[int, list[Card]] = {}
            for card in rest.elements():
                by_rank.setdefault(card.rank, []).append(card)
            recovery = []
            for rank, cards in by_rank.items():
                for kind, count, length in ((PatternType.SINGLE, 1, 1), (PatternType.PAIR, 2, 1), (PatternType.TRIPLE, 3, 1), (PatternType.BOMB, 4, 4)):
                    if len(cards) < count or (rank > 14 and count >= 3):
                        continue
                    candidate = Pattern(kind, rank, length, tuple(cards[:count]))
                    if candidate.can_be_played_on(pattern, level=self.level):
                        recovery.append(candidate)
            if recovery:
                regain = max(1.0 - max((self.response_risk(p, seat) for seat in self.opponents), default=0.0) for p in recovery)
                score -= 1.2 * opponent_response * regain
        if self.leads and not is_teammate(self.leads[-1][0], self.player):
            owner, previous = self.leads[-1]
            if previous.type == pattern.type and self.sizes[owner] > 0:
                score += 1.2 * self.response_risk(pattern, owner)
        return score

    def partner_needs_cover(self) -> bool:
        """Whether an enemy can threaten the top before the partner acts again."""
        if self.top is None:
            return False
        for seat in self.order:
            if seat == self.partner:
                break
            if seat in self.opponents and self.response_risk(self.top, seat, finish_only=True) > 0.05:
                return True
        return False

    def can_takeover_in_two(self, pattern: Pattern, remaining: Sequence[Card]) -> bool:
        """A legal second play and a worthwhile, sufficiently controlled takeover.

        ``remaining`` is exclusively the actor's own residual hand. A partner
        close to going out keeps control unless covering an immediate exit;
        a bomb needs evidence that the lead can come back.
        """
        if (
            not remaining or len(remaining) > 10
        ):
            return False
        # A partner already close to going out normally keeps the lead.
        # Otherwise a controlled two-play exit can be useful without an
        # arbitrary five-card size difference or a four-card first move.
        cover = self.partner_needs_cover()
        if not cover and 0 < self.sizes[self.partner] <= 3:
            return False
        if not cover and self.sizes[self.partner] < self.sizes[self.player]:
            return False
        # No legal pattern exceeds ten cards. Avoid enumerating every
        # structure in a long residual hand just to reject a two-play exit.
        if find_complete_pattern(list(remaining), self.wild) is None:
            return False
        if not is_bomb_type(pattern.type):
            return max((self.response_risk(pattern, seat) for seat in self.opponents), default=0.0) <= 0.2
        # The cheap marginal model does not enumerate unknown straight
        # flushes. Do not infer that a four/five-card bomb is uncontested
        # against an unrevealed five-card-or-larger hand from that omission.
        unmodeled_flush = (
            (pattern.type == PatternType.BOMB and len(pattern.cards) <= 5)
            or (pattern.type == PatternType.STRAIGHT_FLUSH and pattern.rank < 14)
        )
        if unmodeled_flush and any(
            self.sizes[seat] >= 5 and len(self.known[seat]) < self.sizes[seat]
            for seat in self.opponents
        ):
            return False
        return max((self.response_risk(pattern, seat) for seat in self.opponents), default=0.0) <= 0.05

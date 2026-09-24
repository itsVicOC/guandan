"""Frontend-neutral, display-only arrangements of a player's hand."""
from __future__ import annotations

from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass
from itertools import combinations, groupby
from typing import Literal, Sequence

from ..engine.card import Card
from ..engine.hand import Pattern, PatternType, comparison_rank, effective_rank
from ..engine.rules.patterns import detect_patterns, find_complete_pattern
from .formatting import pattern_type_label, rank_value_label

FOCUS_TYPES = (
    PatternType.FOUR_JOKERS,
    PatternType.BOMB,
    PatternType.STRAIGHT_FLUSH,
    PatternType.TRIPLE_SEQUENCE,
    PatternType.PAIR_SEQUENCE,
    PatternType.STRAIGHT,
    PatternType.TRIPLE_PAIR,
    PatternType.TRIPLE,
    PatternType.PAIR,
)
_TYPE_ORDER = {pattern_type: index for index, pattern_type in enumerate(FOCUS_TYPES)}
_DISPLAY_ORDER = _TYPE_ORDER
_TYPE_BONUS = {
    # Keeping a power group is worth more than saving a few extra loose cards.
    PatternType.FOUR_JOKERS: 1100,
    PatternType.BOMB: 1000,
    PatternType.STRAIGHT_FLUSH: 1000,
    PatternType.TRIPLE_SEQUENCE: 12,
    PatternType.PAIR_SEQUENCE: 12,
    PatternType.STRAIGHT: 10,
    PatternType.TRIPLE_PAIR: 8,
    PatternType.TRIPLE: 4,
    PatternType.PAIR: 0,
}
LayoutKind = Literal["pattern", "rank", "suit", "count"]
_BEAM_WIDTH = 40
_BRANCH_WIDTH = 18


@dataclass(frozen=True)
class HandGroup:
    cards: tuple[Card, ...]
    label: str
    pattern: Pattern | None = None
    locked: bool = False


@dataclass(frozen=True)
class HandArrangement:
    kind: LayoutKind
    groups: tuple[HandGroup, ...]
    focus: PatternType | None = None

    @property
    def cards(self) -> tuple[Card, ...]:
        return tuple(card for group in self.groups for card in group.cards)

    @property
    def name(self) -> str:
        if self.kind == "pattern":
            return "牌型·综合" if self.focus is None else f"{pattern_type_label(self.focus)}优先"
        return {"rank": "点数理", "suit": "花色理", "count": "张数理"}[self.kind]

    @property
    def summary(self) -> str:
        if self.kind == "pattern":
            groups = sum(group.pattern is not None for group in self.groups)
            loose = sum(len(group.cards) for group in self.groups if group.pattern is None)
            return f"{groups} 组牌型 · {loose} 张散牌"
        return f"{len(self.groups)} 组"

    @property
    def group_starts(self) -> frozenset[int]:
        starts: set[int] = set()
        position = 0
        for group in self.groups:
            if position:
                starts.add(position)
            position += len(group.cards)
        return frozenset(starts)


def _card_key(card: Card) -> tuple[int, int]:
    return card.rank, int(card.suit)


def _pattern_key(pattern: Pattern, level: int) -> tuple:
    return (
        -len(pattern.cards),
        pattern.wild_used,
        _TYPE_ORDER[pattern.type],
        -comparison_rank(pattern, level),
        tuple(sorted(_card_key(card) for card in pattern.cards)),
    )


def _valid_candidates(
    cards: Sequence[Card], wild_card: Card | None, level: int
) -> list[Pattern]:
    available = Counter(cards)
    best: dict[tuple[PatternType, tuple[tuple[Card, int], ...]], Pattern] = {}

    def consider(pattern: Pattern) -> None:
        if len(pattern.cards) < 2 or pattern.type not in _TYPE_ORDER:
            return
        used = Counter(pattern.cards)
        if any(used[card] > available[card] for card in used):
            return
        signature = (pattern.type, tuple(sorted(used.items(), key=lambda item: _card_key(item[0]))))
        previous = best.get(signature)
        if previous is None or _pattern_key(pattern, level) < _pattern_key(previous, level):
            best[signature] = pattern

    for pattern in detect_patterns(cards, wild_card):
        consider(pattern)

    # The rules detector returns a representative pair/triple per rank. A hand
    # partition also needs the other suit combinations so two disjoint groups
    # of the same rank can be kept together.
    by_rank: dict[int, list[Card]] = {}
    for card in cards:
        if card != wild_card:
            by_rank.setdefault(card.rank, []).append(card)
    for rank, ranked_cards in by_rank.items():
        for size, kind in ((2, PatternType.PAIR), (3, PatternType.TRIPLE)):
            if size == 3 and ranked_cards[0].is_joker:
                continue
            for chosen in combinations(ranked_cards, size):
                consider(Pattern(kind, rank, 1, chosen))
    return sorted(best.values(), key=lambda pattern: _pattern_key(pattern, level))


@dataclass(frozen=True)
class _Candidate:
    pattern: Pattern
    usage: tuple[tuple[int, int], ...]
    reward: int


@dataclass(frozen=True)
class _SearchState:
    remaining: tuple[int, ...]
    chosen: tuple[int, ...]
    score: int
    wild_used: int


def _state_rank(state: _SearchState) -> tuple:
    return (state.score, -sum(state.remaining), -state.wild_used,
            tuple(-index for index in state.chosen))


def _search_partition(
    cards: Sequence[Card], patterns: list[Pattern], focus: PatternType | None, level: int
) -> list[Pattern]:
    """Bounded search for a low-fragmentation partition of a 27-card hand."""
    distinct = tuple(dict.fromkeys(cards))
    card_indices = {card: index for index, card in enumerate(distinct)}
    counts = Counter(cards)
    initial = _SearchState(tuple(counts[card] for card in distinct), (), 0, 0)
    candidates: list[_Candidate] = []
    for pattern in patterns:
        usage = tuple(sorted(
            (card_indices[card], count) for card, count in Counter(pattern.cards).items()
        ))
        reward = (len(pattern.cards) - 1) * 100 - pattern.wild_used * 18
        reward += _TYPE_BONUS[pattern.type] + (24 if focus == pattern.type else 0)
        candidates.append(_Candidate(pattern, usage, reward))
    ranked = sorted(
        range(len(candidates)),
        key=lambda index: (-candidates[index].reward,
                           _pattern_key(candidates[index].pattern, level)),
    )

    def take(state: _SearchState, index: int) -> _SearchState:
        candidate = candidates[index]
        remaining = list(state.remaining)
        for position, count in candidate.usage:
            remaining[position] -= count
        return _SearchState(
            tuple(remaining), (*state.chosen, index),
            state.score + candidate.reward,
            state.wild_used + candidate.pattern.wild_used,
        )

    if focus is None:
        beam = [initial]
    else:
        focused = [index for index in ranked if candidates[index].pattern.type == focus]
        beam = [take(initial, index) for index in focused[:_BEAM_WIDTH]]
    best = max(beam, key=_state_rank)

    for _ in range(len(cards) // 2 + 1):
        successors: dict[tuple[int, ...], _SearchState] = {}
        for state in beam:
            fitting = [
                index for index in ranked
                if all(state.remaining[pos] >= count for pos, count in candidates[index].usage)
            ]
            branches = fitting[:_BRANCH_WIDTH]
            family_counts: Counter[PatternType] = Counter()
            for index in fitting:
                kind = candidates[index].pattern.type
                if family_counts[kind] < 2:
                    branches.append(index)
                    family_counts[kind] += 1
            for index in dict.fromkeys(branches):
                successor = take(state, index)
                previous = successors.get(successor.remaining)
                if previous is None or _state_rank(successor) > _state_rank(previous):
                    successors[successor.remaining] = successor
        if not successors:
            break
        beam = sorted(
            successors.values(),
            key=lambda state: (state.score + 55 * sum(state.remaining), _state_rank(state)),
            reverse=True,
        )[:_BEAM_WIDTH]
        current = max(beam, key=_state_rank)
        if _state_rank(current) > _state_rank(best):
            best = current
    return [candidates[index].pattern for index in best.chosen]


def _pattern_layout(
    cards: Sequence[Card], patterns: list[Pattern], focus: PatternType | None, level: int
) -> HandArrangement:
    positions = {card: index for index, card in enumerate(cards)}
    chosen = _search_partition(cards, patterns, focus, level)
    chosen.sort(key=lambda pattern: (
        0 if focus == pattern.type else 1,
        _DISPLAY_ORDER[pattern.type], -len(pattern.cards),
        -comparison_rank(pattern, level), _pattern_key(pattern, level),
    ))
    remaining = Counter(cards)
    groups: list[HandGroup] = []
    for pattern in chosen:
        remaining.subtract(Counter(pattern.cards))
        group_cards = tuple(sorted(pattern.cards, key=lambda card: positions[card]))
        groups.append(HandGroup(group_cards, pattern_type_label(pattern.type), pattern))
    loose: list[Card] = []
    for card in cards:
        if remaining[card] > 0:
            loose.append(card)
            remaining[card] -= 1
    groups.extend(HandGroup((card,), "散牌") for card in loose)
    return HandArrangement("pattern", tuple(groups), focus)


def _basic_layout(cards: Sequence[Card], kind: LayoutKind, level: int) -> HandArrangement:
    base = list(cards)
    if kind == "rank":
        ordered = base
    elif kind == "suit":
        ordered = sorted(base, key=lambda card: int(card.suit))
    else:
        counts = Counter(card.rank for card in base)
        positions = {card: index for index, card in enumerate(base)}
        ordered = sorted(base, key=lambda card: (
            -counts[card.rank], -effective_rank(card.rank, level), positions[card]
        ))

    def group_key(card: Card) -> int:
        return int(card.suit) if kind == "suit" else card.rank

    groups = []
    for _, iterator in groupby(ordered, key=group_key):
        group = list(iterator)
        if kind == "suit":
            label = group[0].suit.cn
        elif kind == "count":
            label = f"{len(group)}张"
        else:
            label = group[0].short if group[0].is_joker else f"{rank_value_label(group[0].rank)}点"
        groups.append(HandGroup(tuple(group), label))
    return HandArrangement(kind, tuple(groups))


def build_hand_arrangements(
    base_cards: Sequence[Card], wild_card: Card | None, level: int
) -> tuple[HandArrangement, ...]:
    """Build tactical layouts and familiar rank, suit and count views."""
    if len(base_cards) < 2:
        return ()
    candidates = _valid_candidates(base_cards, wild_card, level)
    layouts: list[HandArrangement] = []
    if candidates:
        layouts.append(_pattern_layout(base_cards, candidates, None, level))
        seen = {tuple((group.cards, group.label) for group in layouts[0].groups)}
        for focus in FOCUS_TYPES:
            if not any(pattern.type == focus for pattern in candidates):
                continue
            layout = _pattern_layout(base_cards, candidates, focus, level)
            signature = tuple((group.cards, group.label) for group in layout.groups)
            if signature not in seen:
                layouts.append(layout)
                seen.add(signature)
    for kind in ("rank", "suit", "count"):
        layouts.append(_basic_layout(base_cards, kind, level))
    return tuple(layouts)


def remap_selected_indices(
    previous_cards: Sequence[Card], selected_indices: set[int], new_cards: Sequence[Card]
) -> set[int]:
    """Keep the selected occurrence when identical cards from both decks move."""
    seen: Counter[Card] = Counter()
    selected: set[tuple[Card, int]] = set()
    for index, card in enumerate(previous_cards):
        seen[card] += 1
        if index in selected_indices:
            selected.add((card, seen[card]))
    seen.clear()
    result: set[int] = set()
    for index, card in enumerate(new_cards):
        seen[card] += 1
        if (card, seen[card]) in selected:
            result.add(index)
    return result


class HandOrganizer:
    """Keep manual groups and the selected layout stable across hand changes."""

    def __init__(self) -> None:
        self._key: tuple[tuple[Card, ...], Card | None, int, str | None] | None = None
        self._hand_id: str | None = None
        self._base_cards: tuple[Card, ...] = ()
        self._wild_card: Card | None = None
        self._level = 2
        self._locked: list[HandGroup] = []
        self._arrangements: tuple[HandArrangement, ...] = ()
        self._index = -1
        self._activated = False

    def sync(
        self, base_cards: Sequence[Card], wild_card: Card | None, level: int,
        *, hand_id: str | None = None,
    ) -> None:
        key = (tuple(base_cards), wild_card, level, hand_id)
        if key == self._key:
            return
        previous = self.current
        identity = (previous.kind, previous.focus) if previous else ("pattern", None)
        if hand_id is not None and self._hand_id is not None and hand_id != self._hand_id:
            self._locked.clear()
            self._activated = False
        self._hand_id = hand_id
        self._key = key
        self._base_cards = tuple(base_cards)
        self._wild_card = wild_card
        self._level = level
        self._reconcile_locks()
        self._rebuild_arrangements(identity)

    def _free_cards(self) -> tuple[Card, ...]:
        remaining = Counter(card for group in self._locked for card in group.cards)
        free = []
        for card in self._base_cards:
            if remaining[card]:
                remaining[card] -= 1
            else:
                free.append(card)
        return tuple(free)

    def _reconcile_locks(self) -> None:
        available = Counter(self._base_cards)
        kept: list[HandGroup] = []
        for group in self._locked:
            used = Counter(group.cards)
            if any(used[card] > available[card] for card in used):
                continue
            pattern = find_complete_pattern(group.cards, self._wild_card)
            if pattern is None:
                continue
            available.subtract(used)
            kept.append(HandGroup(group.cards, pattern_type_label(pattern.type), pattern, True))
        self._locked = kept

    def _rebuild_arrangements(self, identity: tuple[LayoutKind, PatternType | None]) -> None:
        self._arrangements = build_hand_arrangements(
            self._free_cards(), self._wild_card, self._level
        )
        if self._activated and self._arrangements:
            self._index = next(
                (index for index, item in enumerate(self._arrangements)
                 if (item.kind, item.focus) == identity),
                0,
            )
        else:
            self._index = -1

    def lock_action(self, selected_indices: Collection[int]) -> Literal["lock", "unlock"] | None:
        chosen = set(selected_indices)
        cards = self.cards
        if not chosen or any(index < 0 or index >= len(cards) for index in chosen):
            return None
        start = 0
        for group in self._locked:
            end = start + len(group.cards)
            indices = set(range(start, end))
            if chosen == indices:
                return "unlock"
            if chosen & indices:
                return None
            start = end
        selected = tuple(cards[index] for index in sorted(chosen))
        if len(selected) < 2 or find_complete_pattern(selected, self._wild_card) is None:
            return None
        return "lock"

    def toggle_lock(self, selected_indices: Collection[int]) -> Literal["locked", "unlocked"] | None:
        action = self.lock_action(selected_indices)
        if action is None:
            return None
        previous = self.current
        identity = (previous.kind, previous.focus) if previous else ("pattern", None)
        if action == "unlock":
            chosen = set(selected_indices)
            start = 0
            for index, group in enumerate(self._locked):
                end = start + len(group.cards)
                if chosen == set(range(start, end)):
                    del self._locked[index]
                    self._rebuild_arrangements(identity)
                    return "unlocked"
                start = end
        else:
            selected = tuple(self.cards[index] for index in sorted(set(selected_indices)))
            pattern = find_complete_pattern(selected, self._wild_card)
            assert pattern is not None
            self._locked.append(
                HandGroup(selected, pattern_type_label(pattern.type), pattern, True)
            )
            self._rebuild_arrangements(identity)
            return "locked"
        return None

    def advance(self) -> bool:
        if not self._arrangements:
            return False
        self._activated = True
        self._index = (self._index + 1) % len(self._arrangements)
        return True

    def select(self, index: int) -> bool:
        if not 0 <= index < len(self._arrangements):
            return False
        self._activated = True
        self._index = index
        return True

    def reset(self) -> None:
        self._activated = False
        self._index = -1

    @property
    def arrangements(self) -> tuple[HandArrangement, ...]:
        return self._arrangements

    @property
    def current(self) -> HandArrangement | None:
        return None if self._index < 0 else self._arrangements[self._index]

    @property
    def locked_count(self) -> int:
        return len(self._locked)

    @property
    def display_groups(self) -> tuple[HandGroup, ...]:
        current = self.current
        if current is not None:
            return (*self._locked, *current.groups)
        if self._locked:
            loose = tuple(HandGroup((card,), "散牌") for card in self._free_cards())
            return (*self._locked, *loose)
        return ()

    @property
    def available(self) -> bool:
        return bool(self._arrangements)

    @property
    def cards(self) -> tuple[Card, ...]:
        current = self.current
        if current is None and not self._locked:
            return self._base_cards
        return (*self._locked_cards(), *(self._free_cards() if current is None else current.cards))

    def _locked_cards(self) -> tuple[Card, ...]:
        return tuple(card for group in self._locked for card in group.cards)

    @property
    def group_starts(self) -> frozenset[int]:
        starts: set[int] = set()
        position = 0
        for group in self.display_groups:
            if position:
                starts.add(position)
            position += len(group.cards)
        return frozenset(starts)

    @property
    def status(self) -> str:
        current = self.current
        layout = "" if current is None else f"{current.name} {self._index + 1}/{len(self._arrangements)}"
        locked = f"已锁 {len(self._locked)} 组" if self._locked else ""
        return " · ".join(part for part in (layout, locked) if part)

    def playable_group_at(self, index: int) -> tuple[int, int, HandGroup] | None:
        start = 0
        for group in self.display_groups:
            end = start + len(group.cards)
            if start <= index < end:
                return (start, end, group) if group.pattern is not None else None
            start = end
        return None

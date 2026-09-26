"""Legal AI tribute choices using only the choosing player's hand."""
from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from ..engine.card import Card
from ..engine.events import TributeSent
from ..engine.rules.tributes import (
    apply_tribute_flow,
    legal_return_cards,
    legal_tribute_cards,
)
from .hand_plan import estimate_remaining_plays, remaining_cards


def _choice_score(hand: list[Card], card: Card, wild: Card | None, level: int, tier: int) -> float:
    if tier == 0:
        return float(card.rank)
    after = remaining_cards(hand, (card,))
    width = 12 if tier == 1 else 24
    score = estimate_remaining_plays(after, wild, level, width=width)
    # The receiving opponent's hand is unknown.  A central rank is more likely
    # to join sequences, but this is deliberately a weak public-information risk.
    score += 0.04 * max(0, 4 - abs(card.rank - 7)) if tier >= 2 else 0.0
    return score


def choose_ai_tribute_cards(
    finish_order: Sequence[int],
    hands: list[list[Card]],
    *,
    level: int,
    wild_card: Card | None,
    difficulties: Sequence[int | None],
    human_choice: tuple[int, str, Card] | None = None,
) -> tuple[dict[int, Card], dict[int, Card]]:
    """Choose every AI tribute/return card without reading recipients' hands.

    A rule-engine preview establishes who gives to whom.  Scoring each choice
    receives only that seat's own hand and public rule parameters.
    """
    if len(finish_order) < 3:
        return {}, {}
    tribute_choices: dict[int, Card] = {}
    return_choices: dict[int, Card] = {}
    third = finish_order[2]
    last = next(seat for seat in range(4) if seat not in finish_order)
    payers = [last] if third % 2 != last % 2 else [third, last]
    for seat in payers:
        difficulty = difficulties[seat]
        if human_choice is not None and human_choice[:2] == (seat, "tribute"):
            tribute_choices[seat] = human_choice[2]
        elif difficulty is not None:
            legal = legal_tribute_cards(hands[seat], wild_card, level)
            if legal:
                tribute_choices[seat] = min(
                    legal,
                    key=lambda card: _choice_score(
                        hands[seat], card, wild_card, level, cast(int, difficulty)
                    ),
                )

    preview_hands = [list(hand) for hand in hands]
    preview = apply_tribute_flow(
        list(finish_order),
        preview_hands,
        level=level,
        wild_card=wild_card,
        tribute_choices=tribute_choices,
    )
    before_returns = [list(hand) for hand in hands]
    for event in preview.events:
        if isinstance(event, TributeSent):
            before_returns[event.from_player].remove(event.card)
            before_returns[event.to_player].append(event.card)
    for exchange in preview.exchanges:
        seat = exchange.to_player
        difficulty = difficulties[seat]
        if human_choice is not None and human_choice[:2] == (seat, "return"):
            return_choices[seat] = human_choice[2]
        elif difficulty is not None:
            legal = legal_return_cards(before_returns[seat], level)
            if legal:
                return_choices[seat] = min(
                    legal,
                    key=lambda card: _choice_score(
                        before_returns[seat], card, wild_card, level, cast(int, difficulty)
                    ),
                )
    return tribute_choices, return_choices

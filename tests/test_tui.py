"""TUI interaction regressions."""
from __future__ import annotations

import asyncio

from guandan.engine.card import Card, Suit
from guandan.engine.state import GameState
from guandan.tui.app import GuandanApp
from guandan.tui.screens.game import GameScreen


def test_duplicate_cards_are_selected_by_position() -> None:
    """Two equal cards from different decks must not toggle together."""
    async def run() -> None:
        duplicate = Card(5, Suit.HEARTS)
        state = GameState(
            level=2,
            wild_card=None,
            hands=[
                [Card(7, Suit.SPADES), duplicate, duplicate],
                [],
                [],
                [],
            ],
            turn_index=0,
            leader=0,
        )

        app = GuandanApp()
        async with app.run_test() as pilot:
            screen = GameScreen(difficulty=0, existing_state=state)
            app.push_screen(screen)
            await pilot.pause()

            await pilot.press("right")
            await pilot.press("space")
            await pilot.pause()

            assert screen._hand_selected_indices == {1}

    asyncio.run(run())

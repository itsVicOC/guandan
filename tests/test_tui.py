"""TUI interaction regressions."""
from __future__ import annotations

import asyncio

from rich.text import Text

from guandan.engine.card import RANK_BIG_JOKER, RANK_SMALL_JOKER, Card, Suit
from guandan.engine.state import GameState
from guandan.tui.app import GuandanApp
from guandan.tui.screens.game import GameScreen, _tui_card


def _plain(markup: str) -> str:
    return Text.from_markup(markup).plain


def test_tui_card_uses_chinese_suit_labels() -> None:
    assert "红5" in _plain(_tui_card(Card(5, Suit.HEARTS)))
    assert "方10" in _plain(_tui_card(Card(10, Suit.DIAMONDS)))
    assert "黑A" in _plain(_tui_card(Card(14, Suit.SPADES)))
    assert "梅K" in _plain(_tui_card(Card(13, Suit.CLUBS)))
    assert "大王" in _plain(_tui_card(Card(RANK_BIG_JOKER, Suit.BIG_JOKER)))
    assert "小王" in _plain(_tui_card(Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER)))


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


def test_jokers_remain_visible_after_cursor_moves() -> None:
    """Cursor highlighting must not hide joker labels during hand redraw."""
    async def run() -> None:
        state = GameState(
            level=2,
            wild_card=None,
            hands=[
                [
                    Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
                    Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER),
                    Card(14, Suit.SPADES),
                ],
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

            hand = screen.query_one("#my-hand")
            assert "大王" in _plain(hand.content)
            assert "小王" in _plain(hand.content)

            await pilot.press("right")
            await pilot.pause()

            assert "大王" in _plain(hand.content)
            assert "小王" in _plain(hand.content)

            await pilot.press("right")
            await pilot.pause()

            assert "大王" in _plain(hand.content)
            assert "小王" in _plain(hand.content)

    asyncio.run(run())

"""TUI interaction regressions."""
from __future__ import annotations

import asyncio

from rich.text import Text

from guandan.engine.card import (
    RANK_2,
    RANK_6,
    RANK_7,
    RANK_8,
    RANK_BIG_JOKER,
    RANK_J,
    RANK_SMALL_JOKER,
    Card,
    Suit,
)
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.state import GameState, pass_turn, play_pattern
from guandan.tui.app import GuandanApp
from guandan.tui.screens.game import GameScreen, _tui_card


def _plain(markup: str) -> str:
    return Text.from_markup(markup).plain


def _single(card: Card) -> Pattern:
    return Pattern(PatternType.SINGLE, card.rank, 1, (card,), 0)


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


def test_locked_passes_remain_visible_after_later_play() -> None:
    """Earlier passes in the same trick must remain visible after a later press."""
    async def run() -> None:
        state = GameState(
            level=2,
            wild_card=None,
            hands=[
                [Card(RANK_2, Suit.HEARTS), Card(RANK_6, Suit.HEARTS)],
                [Card(RANK_7, Suit.HEARTS)],
                [Card(RANK_8, Suit.HEARTS)],
                [Card(RANK_J, Suit.HEARTS)],
            ],
            turn_index=0,
            leader=0,
        )
        play_pattern(state, 0, _single(Card(RANK_2, Suit.HEARTS)))
        pass_turn(state, 1)
        pass_turn(state, 2)
        play_pattern(state, 3, _single(Card(RANK_J, Suit.HEARTS)))

        app = GuandanApp()
        async with app.run_test() as pilot:
            screen = GameScreen(difficulty=0, existing_state=state)
            app.push_screen(screen)
            await pilot.pause()

            assert screen._locked_passed_players() == [1, 2]
            table = screen.query_one("#table")
            table_text = _plain(table.content)
            assert "南: 过牌" in table_text
            assert "西: 过牌" in table_text

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

"""TUI interaction regressions."""
from __future__ import annotations

import asyncio
import random

from rich.text import Text

from guandan.engine.card import (
    RANK_4,
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
                [Card(RANK_4, Suit.HEARTS), Card(RANK_6, Suit.HEARTS)],
                [Card(RANK_7, Suit.HEARTS)],
                [Card(RANK_8, Suit.HEARTS)],
                [Card(RANK_J, Suit.HEARTS)],
            ],
            turn_index=0,
            leader=0,
        )
        play_pattern(state, 0, _single(Card(RANK_4, Suit.HEARTS)))
        pass_turn(state, 3)
        pass_turn(state, 2)
        play_pattern(state, 1, _single(Card(RANK_7, Suit.HEARTS)))

        app = GuandanApp()
        async with app.run_test() as pilot:
            screen = GameScreen(difficulty=0, existing_state=state)
            app.push_screen(screen)
            await pilot.pause()

            assert screen._locked_passed_players() == [3, 2]
            table = screen.query_one("#table")
            table_text = _plain(table.content)
            assert "北: 过牌" in table_text
            assert "西: 过牌" in table_text

    asyncio.run(run())


def test_ai_leader_continues_until_human_turn() -> None:
    """AI 新一轮领出后，应继续推进后续 AI，直到轮到真人。"""

    async def run() -> None:
        state = GameState(
            level=2,
            wild_card=None,
            hands=[
                [Card(9, Suit.HEARTS)],
                [Card(5, Suit.SPADES)],
                [Card(4, Suit.DIAMONDS)],
                [Card(3, Suit.CLUBS), Card(10, Suit.CLUBS)],
            ],
            turn_index=3,
            leader=3,
        )

        app = GuandanApp()
        async with app.run_test() as pilot:
            screen = GameScreen(difficulty=0, existing_state=state)
            screen._ai_rng = random.Random(0)
            app.push_screen(screen)
            await pilot.pause()

            screen._maybe_ai_turn()

            assert state.turn_index == 0
            assert len(state.table) >= 3
            assert [screen._last_player_of(p) for p in state.table[-3:]] == [3, 2, 1]

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


def test_two_big_jokers_selected_in_tui_play_as_pair() -> None:
    """Duplicate jokers must be played together as a pair, not collapsed to one."""
    async def run() -> None:
        state = GameState(
            level=2,
            wild_card=None,
            hands=[
                [
                    Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
                    Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
                    Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER),
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

            screen.action_toggle_select()
            screen.action_cursor_right()
            screen.action_toggle_select()
            screen.action_play()

            assert len(state.hands[0]) == 1
            assert state.table[-1].type == PatternType.PAIR
            assert state.table[-1].rank == RANK_BIG_JOKER
            assert len(state.table[-1].cards) == 2

    asyncio.run(run())


def test_four_jokers_selected_in_tui_play_as_four_joker_bomb() -> None:
    async def run() -> None:
        state = GameState(
            level=2,
            wild_card=None,
            hands=[
                [
                    Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
                    Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
                    Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER),
                    Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER),
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

            for _ in range(4):
                screen.action_toggle_select()
                screen.action_cursor_right()
            screen.action_play()

            assert len(state.hands[0]) == 0
            assert state.table[-1].type == PatternType.FOUR_JOKERS
            assert len(state.table[-1].cards) == 4

    asyncio.run(run())

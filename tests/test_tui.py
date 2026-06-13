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
from guandan.engine.events import Pass, TurnPlayed
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.state import GameState, next_seat_counterclockwise, pass_turn, play_pattern
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


def test_ai_turn_loop_uses_counterclockwise_order_for_every_human_seat() -> None:
    """任意真人座位下，AI 新 leader 都应按逆时针行动到真人。"""

    async def run_case(human: int) -> None:
        leader = next_seat_counterclockwise(human)
        second = next_seat_counterclockwise(leader)
        third = next_seat_counterclockwise(second)
        hands = [[] for _ in range(4)]
        hands[human] = [Card(9, Suit.HEARTS)]
        hands[leader] = [Card(3, Suit.CLUBS), Card(10, Suit.CLUBS)]
        hands[second] = [Card(4, Suit.DIAMONDS)]
        hands[third] = [Card(5, Suit.SPADES)]
        state = GameState(
            level=2,
            wild_card=None,
            hands=hands,
            turn_index=leader,
            leader=leader,
        )

        app = GuandanApp()
        async with app.run_test() as pilot:
            screen = GameScreen(difficulty=0, human=human, existing_state=state)
            screen._ai_rng = random.Random(0)
            app.push_screen(screen)
            await pilot.pause()

            screen._maybe_ai_turn()

            played_players = [
                ev.player for ev in state.history if isinstance(ev, TurnPlayed)
            ]
            assert state.turn_index == human
            assert played_players[-3:] == [leader, second, third]

    async def run() -> None:
        for human in range(4):
            await run_case(human)

    asyncio.run(run())


def test_tui_current_pass_order_ignores_previous_tricks() -> None:
    """当前轮过牌显示不能被旧轮次同玩家过牌顺序污染。"""

    async def run() -> None:
        first = _single(Card(RANK_4, Suit.HEARTS))
        press = _single(Card(RANK_7, Suit.HEARTS))
        state = GameState(
            level=2,
            wild_card=None,
            hands=[
                [Card(RANK_6, Suit.HEARTS)],
                [],
                [],
                [],
            ],
            turn_index=0,
            table=[first, press],
            passed_players={2, 3},
            leader=0,
            history=[
                Pass(player=2, hand_remaining=3),
                Pass(player=3, hand_remaining=3),
                TurnPlayed(player=0, pattern=first, hand_remaining=1),
                Pass(player=3, hand_remaining=1),
                Pass(player=2, hand_remaining=1),
                TurnPlayed(player=1, pattern=press, hand_remaining=0),
            ],
        )

        app = GuandanApp()
        async with app.run_test() as pilot:
            screen = GameScreen(difficulty=0, existing_state=state)
            app.push_screen(screen)
            await pilot.pause()

            assert screen._locked_passed_players() == [3, 2]
            table = screen.query_one("#table")
            lines = _plain(table.content).splitlines()
            assert lines.index("  北: 过牌") < lines.index("  西: 过牌")

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

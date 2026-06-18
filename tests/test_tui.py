"""TUI interaction regressions."""
from __future__ import annotations

import asyncio
import random

from rich.text import Text
from textual.widgets import Button

from guandan.engine.card import (
    RANK_3,
    RANK_4,
    RANK_5,
    RANK_6,
    RANK_7,
    RANK_8,
    RANK_BIG_JOKER,
    RANK_J,
    RANK_SMALL_JOKER,
    Card,
    Suit,
)
from guandan.engine.events import Pass, TributeReturned, TributeSent, TurnPlayed
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.state import GameState, next_seat_counterclockwise, pass_turn, play_pattern
from guandan.tui.app import GuandanApp
from guandan.tui.layout import (
    RECOMMENDED_COLUMNS,
    RECOMMENDED_LINES,
    should_request_terminal_resize,
    terminal_resize_disabled,
)
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


def test_tui_card_marks_cursor_selection_and_wild() -> None:
    card = Card(5, Suit.HEARTS)

    assert "▶" in _plain(_tui_card(card, cursor=True))
    assert "✓" in _plain(_tui_card(card, selected=True))
    assert "配" in _plain(_tui_card(card, wild=True))
    assert "▶" in _plain(_tui_card(card, selected=True, cursor=True))
    assert "✓" in _plain(_tui_card(card, selected=True, cursor=True))


def test_tui_startup_requests_larger_terminal_when_space_is_small() -> None:
    class FakeTTY:
        def isatty(self) -> bool:
            return True

    env = {"TERM": "xterm-256color"}

    assert should_request_terminal_resize(
        RECOMMENDED_COLUMNS - 1,
        RECOMMENDED_LINES,
        env=env,
        stream=FakeTTY(),  # type: ignore[arg-type]
    )
    assert should_request_terminal_resize(
        RECOMMENDED_COLUMNS,
        RECOMMENDED_LINES - 1,
        env=env,
        stream=FakeTTY(),  # type: ignore[arg-type]
    )
    assert not should_request_terminal_resize(
        RECOMMENDED_COLUMNS,
        RECOMMENDED_LINES,
        env=env,
        stream=FakeTTY(),  # type: ignore[arg-type]
    )


def test_tui_startup_resize_can_be_disabled_for_managed_terminals() -> None:
    class FakeTTY:
        def isatty(self) -> bool:
            return True

    assert terminal_resize_disabled({"GUANDAN_TUI_NO_RESIZE": "1"})
    assert not should_request_terminal_resize(
        80,
        24,
        env={"TERM": "xterm-256color", "TMUX": "1"},
        stream=FakeTTY(),  # type: ignore[arg-type]
    )
    assert not should_request_terminal_resize(
        80,
        24,
        env={"TERM": "xterm-256color", "GUANDAN_TUI_NO_RESIZE": "true"},
        stream=FakeTTY(),  # type: ignore[arg-type]
    )


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


def test_table_display_clears_only_current_player_previous_action() -> None:
    """出牌区只在轮到某玩家时清理该玩家上一轮次展示。"""

    async def run() -> None:
        old_actions = {
            0: ("play", _single(Card(RANK_4, Suit.HEARTS))),
            3: ("play", _single(Card(RANK_6, Suit.HEARTS))),
            2: ("pass", None),
            1: ("play", _single(Card(RANK_8, Suit.HEARTS))),
        }
        state = GameState(
            level=2,
            wild_card=None,
            hands=[[Card(RANK_J, Suit.HEARTS)], [], [], []],
            turn_index=0,
            leader=0,
            table=[],
        )

        app = GuandanApp()
        async with app.run_test() as pilot:
            screen = GameScreen(difficulty=0, existing_state=state)
            app.push_screen(screen)
            await pilot.pause()

            screen._displayed_table_actions = dict(old_actions)
            screen._last_display_turn = 3
            screen._refresh_all()

            table = screen.query_one("#table")
            table_text = _plain(table.content)
            assert "东: --" in table_text
            assert "红4" not in table_text
            assert "北:" in table_text
            assert "西: 过牌" in table_text
            assert "南:" in table_text

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


def test_finished_game_can_start_next_round_from_head_team_level() -> None:
    """下一局应以头游所在队伍的最终级牌重新发牌。"""
    async def run() -> None:
        state = GameState(
            level=2,
            wild_card=None,
            hands=[[], [], [], []],
            turn_index=0,
            leader=0,
            finish_order=[1, 3, 0],
            finished=True,
        )
        state.team_levels_final = [2, 5]  # type: ignore[attr-defined]

        app = GuandanApp()
        async with app.run_test() as pilot:
            screen = GameScreen(difficulty=0, existing_state=state, human=0)
            screen._game_saved = True
            app.push_screen(screen)
            await pilot.pause()

            next_button = screen.query_one("#btn-next-game", Button)
            assert next_button.disabled is False
            assert "级牌 5" in str(next_button.label)

            screen.action_next_game()
            await pilot.pause()

            assert screen.state is not state
            assert screen.state is not None
            assert screen.state.level == 5
            assert screen.state.team_levels == [2, 5]
            assert screen.state.finished is False
            assert len(screen.state.hands[0]) == 27
            assert screen._game_saved is False
            assert "新一局开始" in screen._last_action

    asyncio.run(run())


def test_next_round_applies_tribute_card_swaps_and_records_events() -> None:
    """下一局开始时应真实执行进贡/还贡，而不是只计算先手。"""

    async def run() -> None:
        state = GameState(
            level=2,
            wild_card=None,
            hands=[[], [], [], []],
            turn_index=0,
            leader=0,
            finish_order=[0, 1, 2],
            finished=True,
        )
        state.team_levels_final = [5, 2]

        app = GuandanApp()
        async with app.run_test() as pilot:
            screen = GameScreen(difficulty=0, existing_state=state, human=0)
            screen._game_saved = True
            app.push_screen(screen)
            await pilot.pause()

            fixed_hands = [
                [Card(RANK_3, Suit.HEARTS), Card(RANK_4, Suit.HEARTS)],
                [Card(RANK_4, Suit.SPADES), Card(RANK_6, Suit.SPADES)],
                [Card(RANK_5, Suit.CLUBS), Card(RANK_7, Suit.CLUBS)],
                [Card(RANK_BIG_JOKER, Suit.BIG_JOKER), Card(RANK_8, Suit.CLUBS)],
            ]

            def fake_initial_state(**kwargs) -> GameState:
                return GameState(
                    level=kwargs["level"],
                    wild_card=Card(RANK_5, Suit.HEARTS),
                    hands=[list(hand) for hand in fixed_hands],
                    turn_index=kwargs["first_player"],
                    leader=kwargs["first_player"],
                    team_levels=list(kwargs["team_levels"]),
                )

            from unittest.mock import patch

            with patch("guandan.tui.screens.game.make_initial_state", fake_initial_state):
                screen.action_next_game()
                await pilot.pause()

            assert screen.state is not None
            assert screen.state.turn_index == 3
            assert all(len(hand) == 2 for hand in screen.state.hands)
            assert Card(RANK_BIG_JOKER, Suit.BIG_JOKER) in screen.state.hands[0]
            assert Card(RANK_3, Suit.HEARTS) in screen.state.hands[3]
            assert any(isinstance(event, TributeSent) for event in screen.state.history)
            assert any(isinstance(event, TributeReturned) for event in screen.state.history)

    asyncio.run(run())


def test_match_finished_disables_next_round_button() -> None:
    async def run() -> None:
        state = GameState(
            level=14,
            wild_card=None,
            hands=[[], [], [], []],
            turn_index=0,
            leader=0,
            finish_order=[0, 2, 1],
            finished=True,
            match_finished=True,
            winner_team=0,
        )
        state.team_levels_final = [2, 14]

        app = GuandanApp()
        async with app.run_test() as pilot:
            screen = GameScreen(difficulty=0, existing_state=state, human=0)
            app.push_screen(screen)
            await pilot.pause()

            next_button = screen.query_one("#btn-next-game", Button)
            assert next_button.disabled is True
            assert "比赛已结束" in str(next_button.label)

    asyncio.run(run())


def test_next_round_first_player_uses_last_when_third_and_last_different_teams() -> None:
    async def run() -> None:
        state = GameState(
            level=2,
            wild_card=None,
            hands=[[], [], [], []],
            turn_index=0,
            leader=0,
            finish_order=[0, 1, 2],  # 三游西，末游北，不同队
            finished=True,
        )
        hands = [
            [Card(RANK_4, Suit.HEARTS)],
            [Card(RANK_BIG_JOKER, Suit.BIG_JOKER)],
            [Card(RANK_4, Suit.SPADES)],
            [Card(RANK_6, Suit.CLUBS)],
        ]

        app = GuandanApp()
        async with app.run_test() as pilot:
            screen = GameScreen(difficulty=0, existing_state=state, human=0)
            app.push_screen(screen)
            await pilot.pause()
            assert screen._next_round_first_player_for_hands(state, hands) == 3

    asyncio.run(run())


def test_next_round_first_player_compares_double_tribute_cards() -> None:
    async def run() -> None:
        state = GameState(
            level=2,
            wild_card=None,
            hands=[[], [], [], []],
            turn_index=0,
            leader=0,
            finish_order=[0, 2, 1],  # 三游南，末游北，同为下游方
            finished=True,
        )
        hands = [
            [Card(RANK_4, Suit.HEARTS)],
            [Card(RANK_BIG_JOKER, Suit.BIG_JOKER)],
            [Card(RANK_4, Suit.SPADES)],
            [Card(RANK_8, Suit.CLUBS)],
        ]

        app = GuandanApp()
        async with app.run_test() as pilot:
            screen = GameScreen(difficulty=0, existing_state=state, human=0)
            app.push_screen(screen)
            await pilot.pause()
            assert screen._next_round_first_player_for_hands(state, hands) == 1

    asyncio.run(run())


def test_next_round_first_player_uses_next_level_wild_card() -> None:
    async def run() -> None:
        state = GameState(
            level=2,
            wild_card=None,
            hands=[[], [], [], []],
            turn_index=0,
            leader=0,
            finish_order=[0, 2, 1],  # 三游南，末游北，同为下游方
            finished=True,
        )
        state.team_levels_final = [5, 2]
        hands = [
            [Card(RANK_4, Suit.HEARTS)],
            [Card(RANK_5, Suit.HEARTS), Card(RANK_7, Suit.CLUBS)],
            [Card(RANK_4, Suit.SPADES)],
            [Card(RANK_8, Suit.CLUBS)],
        ]

        app = GuandanApp()
        async with app.run_test() as pilot:
            screen = GameScreen(difficulty=0, existing_state=state, human=0)
            app.push_screen(screen)
            await pilot.pause()
            assert screen._next_round_first_player_for_hands(state, hands) == 3

    asyncio.run(run())

"""GUI/shared session regressions."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from guandan.engine.card import RANK_3, RANK_4, RANK_5, RANK_8, RANK_BIG_JOKER, Card, Suit
from guandan.engine.events import TributeReturned, TributeSent
from guandan.engine.hand import PatternType, sort_cards
from guandan.engine.state import GameState
from guandan.ui.session import GameSession


def test_session_selects_duplicate_jokers_by_position() -> None:
    state = GameState(
        level=2,
        wild_card=None,
        hands=[
            [
                Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
                Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
                Card(RANK_8, Suit.CLUBS),
            ],
            [],
            [],
            [],
        ],
        turn_index=0,
        leader=0,
    )
    session = GameSession(difficulty=0, existing_state=state, human=0)
    hand = sort_cards(state.hands[0])

    result = session.play_human_cards(hand[:2])

    assert result.ok
    assert len(state.hands[0]) == 1
    assert state.table[-1].type == PatternType.PAIR
    assert len(state.table[-1].cards) == 2


def test_session_visual_seats_match_east_perspective() -> None:
    session = GameSession(difficulty=0, human=0)

    assert session.visual_seats() == {
        "left": 1,
        "opposite": 2,
        "right": 3,
    }


def test_session_next_game_applies_tribute_swaps_and_records_events() -> None:
    finished = GameState(
        level=2,
        wild_card=None,
        hands=[[], [], [], []],
        turn_index=0,
        leader=0,
        finish_order=[0, 1, 2],
        finished=True,
    )
    finished.team_levels_final = [5, 2]
    fixed_hands = [
        [Card(RANK_3, Suit.HEARTS), Card(RANK_4, Suit.HEARTS)],
        [Card(RANK_4, Suit.SPADES), Card(RANK_8, Suit.SPADES)],
        [Card(RANK_5, Suit.CLUBS), Card(RANK_8, Suit.CLUBS)],
        [Card(RANK_BIG_JOKER, Suit.BIG_JOKER), Card(RANK_8, Suit.DIAMONDS)],
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

    session = GameSession(difficulty=0, existing_state=finished, human=0)
    session.game_saved = True
    with patch("guandan.ui.session.make_initial_state", fake_initial_state):
        result = session.start_next_game()

    assert result.ok
    assert session.state is not None
    assert session.state.level == 5
    assert session.state.turn_index == 3
    assert all(len(hand) == 2 for hand in session.state.hands)
    assert Card(RANK_BIG_JOKER, Suit.BIG_JOKER) in session.state.hands[0]
    assert Card(RANK_3, Suit.HEARTS) in session.state.hands[3]
    assert any(isinstance(event, TributeSent) for event in session.state.history)
    assert any(isinstance(event, TributeReturned) for event in session.state.history)


def test_session_retries_finished_save_without_double_counting() -> None:
    finished = GameState(
        level=2,
        wild_card=None,
        hands=[[], [], [], []],
        turn_index=0,
        leader=0,
        finish_order=[0, 1, 2, 3],
        finished=True,
    )
    session = GameSession(difficulty=0, existing_state=finished, human=0, game_id="retry-game")
    profile = {
        "statistics": {
            "total_games": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "by_difficulty": {},
            "recorded_game_ids": [],
        }
    }
    with patch("guandan.ui.session.save_history"), patch(
        "guandan.ui.session.load_profile", return_value=profile
    ), patch("guandan.ui.session.save_profile"), patch(
        "guandan.ui.session.delete_savegame", side_effect=[OSError("busy"), None]
    ):
        assert session.save_finished_if_needed() is False
        assert session.game_saved is False
        assert session.save_finished_if_needed() is True

    assert profile["statistics"]["total_games"] == 1
    assert profile["statistics"]["recorded_game_ids"] == ["retry-game"]


def test_gui_window_smoke_offscreen() -> None:
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    code = (
        "from PySide6.QtWidgets import QApplication; "
        "from guandan.engine.card import Card, Suit; "
        "from guandan.engine.state import make_initial_state; "
        "from guandan.gui.cards import BLACK_SUIT_COLOR, NORMAL_SUIT_FONT_SIZE, RED_SUIT_COLOR, card_palette, gui_suit_name; "
        "from guandan.gui.window import GuandanMainWindow; "
        "from guandan.ui.session import GameSession; "
        "assert card_palette(Card(5, Suit.HEARTS))[0] == RED_SUIT_COLOR; "
        "assert card_palette(Card(5, Suit.DIAMONDS))[0] == RED_SUIT_COLOR; "
        "assert card_palette(Card(5, Suit.SPADES))[0] == BLACK_SUIT_COLOR; "
        "assert card_palette(Card(5, Suit.CLUBS))[0] == BLACK_SUIT_COLOR; "
        "assert gui_suit_name(Suit.DIAMONDS) == '方片'; "
        "assert NORMAL_SUIT_FONT_SIZE >= 44; "
        "app = QApplication([]); "
        "window = GuandanMainWindow(); "
        "assert window.minimumWidth() >= 1080; "
        "assert window.windowTitle().startswith('掼蛋 GUI'); "
        "state = make_initial_state(level=2, first_player=0, seed=1); "
        "window.start_game(GameSession(difficulty=0, existing_state=state, human=0)); "
        "page = window.game_page; "
        "assert page is not None; "
        "assert page.left.title.text().startswith('南家'); "
        "assert page.opposite.title.text().startswith('西家'); "
        "assert page.right.title.text().startswith('北家'); "
        "assert len(page.hand_cards) == 27; "
        "assert page.hand.minimumHeight() >= 200; "
        "page.toggle_card(0); "
        "page.play_selected(); "
        "assert len(state.table) == 1; "
        "assert len(state.hands[0]) == 26; "
        "window.show_replay({'played_at': '2026-07-23T12:00:00', 'events': state.history}); "
        "replay = window.stack.currentWidget(); "
        "assert replay.__class__.__name__ == 'ReplayPage'; "
        "assert replay.event_index == len(state.history) - 1; "
        "replay.set_event_index(0); "
        "assert replay.event_index == 0; "
        "window.game_page = None; "
        "window.close(); "
        "app.processEvents(); "
        "app.quit(); "
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout

"""GUI/shared session regressions."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from copy import deepcopy
from unittest.mock import patch

import pytest

from guandan.engine.card import (
    RANK_2,
    RANK_3,
    RANK_4,
    RANK_5,
    RANK_6,
    RANK_7,
    RANK_8,
    RANK_A,
    RANK_BIG_JOKER,
    RANK_K,
    RANK_SMALL_JOKER,
    Card,
    Suit,
)
from guandan.engine.events import TributeReturned, TributeSent
from guandan.engine.hand import Pattern, PatternType, sort_cards
from guandan.engine.state import GameState
from guandan.storage import DEFAULT_PROFILE
from guandan.ui.session import GameSession


def _profile_transaction(profile: dict):
    def update(mutator):
        return mutator(profile)

    return update


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


def test_gui_display_sort_places_level_between_jokers_and_ace() -> None:
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    from guandan.gui.cards import sort_cards_for_display

    cards = [
        Card(RANK_2, Suit.HEARTS),
        Card(RANK_2, Suit.CLUBS),
        Card(RANK_A, Suit.HEARTS),
        Card(RANK_K, Suit.SPADES),
        Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
        Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER),
    ]

    displayed = sort_cards_for_display(cards, level=RANK_2)

    assert displayed == [
        Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
        Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER),
        Card(RANK_2, Suit.CLUBS),
        Card(RANK_2, Suit.HEARTS),
        Card(RANK_A, Suit.HEARTS),
        Card(RANK_K, Suit.SPADES),
    ]


def test_gui_display_sort_handles_other_level_and_ace_level() -> None:
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    from guandan.gui.cards import sort_cards_for_display

    cards = [
        Card(RANK_A, Suit.HEARTS),
        Card(RANK_5, Suit.CLUBS),
        Card(RANK_5, Suit.HEARTS),
        Card(RANK_K, Suit.SPADES),
        Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
    ]

    assert [card.rank for card in sort_cards_for_display(cards, level=RANK_5)] == [
        RANK_BIG_JOKER,
        RANK_5,
        RANK_5,
        RANK_A,
        RANK_K,
    ]
    assert [card.rank for card in sort_cards_for_display(cards, level=RANK_A)] == [
        RANK_BIG_JOKER,
        RANK_A,
        RANK_K,
        RANK_5,
        RANK_5,
    ]


def test_session_visual_seats_match_east_perspective() -> None:
    session = GameSession(difficulty=0, human=0)

    assert session.visual_seats() == {
        "left": 1,
        "opposite": 2,
        "right": 3,
    }


def test_session_hint_cycles_through_distinct_legal_responses() -> None:
    table_top = Pattern(
        PatternType.SINGLE,
        rank=RANK_5,
        length=1,
        cards=(Card(RANK_5, Suit.SPADES),),
    )
    state = GameState(
        level=RANK_2,
        wild_card=None,
        hands=[
            [
                Card(RANK_8, Suit.CLUBS),
                Card(RANK_8, Suit.CLUBS),
                Card(RANK_K, Suit.HEARTS),
            ],
            [],
            [],
            [],
        ],
        turn_index=0,
        leader=1,
        table=[table_top],
    )
    session = GameSession(difficulty=0, existing_state=state, human=0)

    first = session.hint_for_human()
    second = session.hint_for_human()
    wrapped = session.hint_for_human()

    assert first.ok and second.ok and wrapped.ok
    assert first.suggested_cards != second.suggested_cards
    assert wrapped.suggested_cards == first.suggested_cards
    assert "提示 1/2" in first.message
    assert "提示 2/2" in second.message
    for result in (first, second):
        pattern = Pattern(
            PatternType.SINGLE,
            rank=result.suggested_cards[0].rank,
            length=1,
            cards=result.suggested_cards,
        )
        assert pattern.can_be_played_on(table_top, level=state.level)


def test_session_hint_suggests_pass_when_table_cannot_be_beaten() -> None:
    four_jokers = Pattern(
        PatternType.FOUR_JOKERS,
        rank=RANK_BIG_JOKER,
        length=4,
        cards=(
            Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
            Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
            Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER),
            Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER),
        ),
    )
    state = GameState(
        level=RANK_2,
        wild_card=None,
        hands=[[Card(RANK_K, Suit.HEARTS)], [], [], []],
        turn_index=0,
        leader=1,
        table=[four_jokers],
    )

    result = GameSession(difficulty=0, existing_state=state, human=0).hint_for_human()

    assert result.ok
    assert result.suggested_cards == ()
    assert result.message == "提示：建议过牌"


def test_session_hint_includes_bomb_over_straight_with_unrelated_joker() -> None:
    table_top = Pattern(
        PatternType.STRAIGHT,
        rank=RANK_7,
        length=5,
        cards=(
            Card(RANK_3, Suit.HEARTS),
            Card(RANK_4, Suit.DIAMONDS),
            Card(RANK_5, Suit.SPADES),
            Card(RANK_6, Suit.CLUBS),
            Card(RANK_7, Suit.HEARTS),
        ),
    )
    bomb_cards = (
        Card(RANK_8, Suit.HEARTS),
        Card(RANK_8, Suit.DIAMONDS),
        Card(RANK_8, Suit.SPADES),
        Card(RANK_8, Suit.CLUBS),
    )
    state = GameState(
        level=RANK_2,
        wild_card=None,
        hands=[
            [*bomb_cards, Card(RANK_BIG_JOKER, Suit.BIG_JOKER)],
            [],
            [],
            [],
        ],
        turn_index=0,
        leader=1,
        table=[table_top],
    )

    result = GameSession(difficulty=0, existing_state=state, human=0).hint_for_human()

    assert result.ok
    assert result.suggested_cards == bomb_cards
    assert "炸弹" in result.message


def test_session_game_ids_are_unique_and_filesystem_safe() -> None:
    first = GameSession(difficulty=0)
    second = GameSession(difficulty=0)

    assert first.game_id != second.game_id
    assert first.game_id.startswith("game_")
    assert first.game_id.replace("_", "").isalnum()


def test_session_next_game_uses_selected_human_return_and_records_events() -> None:
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
        prepared = session.prepare_next_game()
        assert session.state is finished
        choice = session.pending_next_game_choice()
        assert choice is not None
        assert choice.kind == "return"
        assert Card(RANK_4, Suit.HEARTS) in choice.cards
        result = session.finalize_next_game(Card(RANK_4, Suit.HEARTS))

    assert result.ok
    assert session.state is not None
    assert session.state.level == 5
    assert session.state.turn_index == 3
    assert all(len(hand) == 2 for hand in session.state.hands)
    assert Card(RANK_BIG_JOKER, Suit.BIG_JOKER) in session.state.hands[0]
    assert Card(RANK_4, Suit.HEARTS) in session.state.hands[3]
    assert Card(RANK_3, Suit.HEARTS) in session.state.hands[0]
    assert any(isinstance(event, TributeSent) for event in session.state.history)
    assert any(isinstance(event, TributeReturned) for event in session.state.history)
    assert prepared.ok


def test_session_cancel_prepared_next_game_keeps_completed_round() -> None:
    finished = GameState(
        level=2,
        wild_card=None,
        hands=[[], [], [], []],
        turn_index=0,
        leader=0,
        finish_order=[0, 1, 2],
        finished=True,
        team_levels_final=[5, 2],
    )
    session = GameSession(
        difficulty=0,
        existing_state=finished,
        human=0,
        game_id="finished-round",
        match_id="same-match",
        round_index=2,
    )
    session.game_saved = True

    assert session.prepare_next_game().ok
    assert session.cancel_next_game().ok

    assert session.state is finished
    assert session.game_id == "finished-round"
    assert session.match_id == "same-match"
    assert session.round_index == 2


def test_session_keeps_match_id_and_advances_round_and_game_ids() -> None:
    finished = GameState(
        level=2,
        wild_card=None,
        hands=[[], [], [], []],
        turn_index=0,
        leader=0,
        finish_order=[0, 1, 2],
        finished=True,
        team_levels_final=[5, 2],
    )
    session = GameSession(
        difficulty=0,
        existing_state=finished,
        game_id="old-round",
        match_id="same-match",
        round_index=4,
    )
    session.game_saved = True

    result = session.start_next_game()

    assert result.ok
    assert session.game_id != "old-round"
    assert session.match_id == "same-match"
    assert session.round_index == 5


def test_session_keeps_finished_state_when_persistence_fails() -> None:
    finished = GameState(
        level=2,
        wild_card=None,
        hands=[[], [], [], []],
        turn_index=0,
        leader=0,
        finish_order=[0, 1, 2],
        finished=True,
        team_levels_final=[5, 2],
    )
    session = GameSession(difficulty=0, existing_state=finished, human=0)

    with patch.object(session, "save_finished_if_needed", return_value=False):
        session.last_action = "保存失败：disk full"
        result = session.start_next_game()

    assert result.ok is False
    assert "保存失败" in result.message
    assert session.state is finished


def test_session_records_round_head_without_counting_a_match() -> None:
    finished = GameState(
        level=2,
        wild_card=None,
        hands=[[], [], [], []],
        turn_index=0,
        leader=1,
        finish_order=[1, 0, 3],
        finished=True,
    )
    session = GameSession(difficulty=0, existing_state=finished, human=0, game_id="team-loss")
    profile = deepcopy(DEFAULT_PROFILE)
    with patch("guandan.ui.session.save_history"), patch(
        "guandan.ui.session.update_profile", side_effect=_profile_transaction(profile)
    ), patch("guandan.ui.session.delete_savegame"):
        assert session.save_finished_if_needed() is True

    assert profile["statistics"]["total_rounds"] == 1
    assert profile["statistics"]["head_rounds"] == 0
    assert profile["statistics"]["total_matches"] == 0


def test_session_records_match_result_only_after_passing_ace() -> None:
    finished = GameState(
        level=RANK_A,
        wild_card=None,
        hands=[[], [], [], []],
        turn_index=0,
        leader=0,
        finish_order=[0, 1, 2, 3],
        finished=True,
        match_finished=True,
        winner_team=0,
    )
    session = GameSession(
        difficulty=0,
        existing_state=finished,
        human=0,
        game_id="final-round",
        match_id="completed-match",
    )
    profile = deepcopy(DEFAULT_PROFILE)
    with patch("guandan.ui.session.save_history"), patch(
        "guandan.ui.session.update_profile", side_effect=_profile_transaction(profile)
    ), patch("guandan.ui.session.delete_savegame"):
        assert session.save_finished_if_needed() is True

    assert profile["statistics"]["total_rounds"] == 1
    assert profile["statistics"]["head_rounds"] == 1
    assert profile["statistics"]["total_matches"] == 1
    assert profile["statistics"]["match_wins"] == 1
    assert profile["statistics"]["recorded_match_ids"] == ["completed-match"]


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
    profile = deepcopy(DEFAULT_PROFILE)
    with patch("guandan.ui.session.save_history"), patch(
        "guandan.ui.session.update_profile", side_effect=_profile_transaction(profile)
    ), patch(
        "guandan.ui.session.delete_savegame", side_effect=[OSError("busy"), None]
    ):
        assert session.save_finished_if_needed() is False
        assert session.game_saved is False
        assert session.save_finished_if_needed() is True

    assert profile["statistics"]["total_rounds"] == 1
    assert profile["statistics"]["recorded_game_ids"] == ["retry-game"]


def test_session_restored_elapsed_time_is_accumulated_when_saving() -> None:
    state = GameState(
        level=2,
        wild_card=None,
        hands=[[], [], [], []],
        turn_index=0,
        leader=0,
    )
    with patch("guandan.ui.session.time.time", return_value=100.0):
        session = GameSession(
            difficulty=0,
            existing_state=state,
            elapsed_seconds=75,
        )
    with patch("guandan.ui.session.time.time", return_value=125.9), patch(
        "guandan.ui.session.save_game"
    ) as save:
        session.save_unfinished()

    assert save.call_args.kwargs["elapsed_seconds"] == 100


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
        "from guandan.gui.window import APP_QSS, GuandanMainWindow; "
        "from guandan.ui.session import GameSession; "
        "assert card_palette(Card(5, Suit.HEARTS))[0] == RED_SUIT_COLOR; "
        "assert card_palette(Card(5, Suit.DIAMONDS))[0] == RED_SUIT_COLOR; "
        "assert card_palette(Card(5, Suit.SPADES))[0] == BLACK_SUIT_COLOR; "
        "assert card_palette(Card(5, Suit.CLUBS))[0] == BLACK_SUIT_COLOR; "
        "assert gui_suit_name(Suit.DIAMONDS) == '方片'; "
        "assert NORMAL_SUIT_FONT_SIZE >= 44; "
        "app = QApplication([]); app.setStyleSheet(APP_QSS); "
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
        "assert 100 <= page.hand.minimumHeight() <= 150; "
        "assert page.play_button.isEnabled() is False; "
        "page.hint(); "
        "first_hint = set(page.selected_indices); "
        "assert first_hint; "
        "assert page.play_button.isEnabled() is True; "
        "page.hint(); "
        "assert page.selected_indices; "
        "assert page.selected_indices != first_hint; "
        "page.clear_selection(); "
        "page.toggle_card(0); "
        "assert page.play_button.isEnabled() is True; "
        "page.play_selected(); "
        "assert len(state.table) == 1; "
        "assert len(state.hands[0]) == 26; "
        "assert '单张' in page.table.rows[0].text(); "
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


def test_gui_stops_ai_when_table_is_hidden_or_ai_fails() -> None:
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    code = """
from unittest.mock import Mock
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from guandan.engine.state import make_initial_state
from guandan.gui.window import GuandanMainWindow
from guandan.ui.session import GameSession, SessionAction

app = QApplication([])
window = GuandanMainWindow()

state = make_initial_state(level=2, first_player=3, seed=9)
session = GameSession(difficulty=0, existing_state=state, human=0)
session.save_unfinished = Mock()
window.start_game(session)
before = len(state.history)
window.game_page.back_to_menu()
loop = QEventLoop()
QTimer.singleShot(500, loop.quit)
loop.exec()
assert len(state.history) == before

failed_state = make_initial_state(level=2, first_player=3, seed=10)
failed_session = GameSession(difficulty=0, existing_state=failed_state, human=0)
failed_session.step_ai = Mock(return_value=SessionAction(False, "AI 错误：invalid"))
window.start_game(failed_session)
loop = QEventLoop()
QTimer.singleShot(700, loop.quit)
loop.exec()
assert failed_session.step_ai.call_count == 1
assert not window.game_page._ai_timer.isActive()

window.game_page = None
window.close()
app.quit()
print("ok")
"""
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


def test_gui_empty_history_and_new_game_conflict_states() -> None:
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    code = """
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QMessageBox
from guandan.engine.state import make_initial_state
from guandan.gui.window import GuandanMainWindow
from guandan.ui.session import GameSession

app = QApplication([])
window = GuandanMainWindow()

with patch("guandan.gui.window.load_history_list", return_value=[]):
    window.show_history()
    history = window.stack.currentWidget()
    assert history.table.isVisible() is False
    assert history.empty.isHidden() is False
    assert history.replay_button.isEnabled() is False

with patch("guandan.gui.window.load_history_list", side_effect=OSError("storage busy")):
    history.refresh()
    assert "无法读取历史记录" in history.empty.text()
    assert "storage busy" in history.empty.text()

with patch.object(
    QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
), patch("guandan.gui.window.has_savegame", return_value=False), patch(
    "guandan.gui.window.delete_savegame", side_effect=OSError("storage busy")
), patch.object(
    QMessageBox, "warning"
) as delete_warning:
    window.show_load()
    load_page = window.stack.currentWidget()
    load_page._delete_save()
    delete_warning.assert_called_once()
    assert window.stack.currentWidget() is load_page

with patch("guandan.gui.window.has_savegame", return_value=True), patch.object(
    QMessageBox, "warning", return_value=QMessageBox.StandardButton.Cancel
):
    assert window.confirm_start_new_game() is False

with patch("guandan.gui.window.has_savegame", return_value=True), patch(
    "guandan.gui.window.delete_savegame"
) as delete, patch.object(
    QMessageBox, "warning", return_value=QMessageBox.StandardButton.Discard
):
    assert window.confirm_start_new_game() is True
    delete.assert_called_once_with()

state = make_initial_state(level=2, first_player=0, seed=7)
session = GameSession(difficulty=0, existing_state=state, human=0)
window.start_game(session)
with patch.object(session, "save_unfinished", side_effect=OSError("disk full")), patch.object(
    QMessageBox, "warning"
) as warning:
    window.game_page.back_to_menu()
    assert window.stack.currentWidget() is window.game_page
    warning.assert_called_once()

window.game_page = None
window.close()
app.quit()
print("ok")
"""
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

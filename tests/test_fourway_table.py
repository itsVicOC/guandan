"""Seat ownership, public-trick lifetime, and compact table geometry."""
from __future__ import annotations

import importlib.util
import os
import random
import subprocess
import sys

import pytest

from guandan.engine.card import Card, Suit
from guandan.engine.events import Pass, TurnPlayed
from guandan.engine.rules.patterns import find_complete_pattern
from guandan.engine.state import (
    CURRENT_RULESET_VERSION,
    LEGACY_RULESET_VERSION,
    GameState,
    make_initial_state,
    pass_turn,
    play_pattern,
)
from guandan.ui.session import GameSession


def _play(state, rank):
    card = next(card for card in state.hands[state.turn_index] if card.rank == rank)
    pattern = find_complete_pattern([card], state.wild_card)
    play_pattern(state, state.turn_index, pattern)
    return pattern


def _visible(state):
    # A fresh session models loading a save without any earlier UI refreshes.
    return GameSession(difficulty=0, existing_state=state).table_display_actions(
        preserve_completed_trick=True
    )


def test_fourway_keeps_historical_passes_and_replaces_the_whole_trick():
    state = GameState(level=2, wild_card=None, hands=[
        [Card(rank, Suit.CLUBS) for rank in ranks]
        for ranks in ([3, 5, 10], [9, 10], [4, 10], [6, 7, 10])
    ], turn_index=0, leader=0)
    east_first = _play(state, 3)
    pass_turn(state, 3)
    west = _play(state, 4)
    pass_turn(state, 1)
    assert _visible(state) == {0: ("play", east_first), 3: ("pass", None),
                               2: ("play", west), 1: ("pass", None)}
    east_second = _play(state, 5)
    north = _play(state, 6)
    assert _visible(state)[0] == ("play", east_second)
    assert _visible(state)[3] == ("play", north)
    for seat in (2, 1, 0):
        pass_turn(state, seat)
    assert not state.table
    closed = _visible(state)
    assert closed == {0: ("pass", None), 3: ("play", north),
                      2: ("pass", None), 1: ("pass", None)}
    lead = _play(state, 7)
    assert _visible(state) == {3: ("play", lead)}


def test_fourway_retains_finished_winner_until_partner_leads():
    state = GameState(level=2, wild_card=None, hands=[
        [Card(3, Suit.CLUBS)], [Card(6, Suit.CLUBS)],
        [Card(5, Suit.CLUBS)], [Card(4, Suit.CLUBS)],
    ], turn_index=0, leader=0)
    winner = _play(state, 3)
    for seat in (3, 2, 1):
        pass_turn(state, seat)
    assert state.turn_index == 2 and state.next_trick_starter == 2
    assert _visible(state)[0] == ("play", winner)
    lead = _play(state, 5)
    assert _visible(state) == {2: ("play", lead)}


@pytest.mark.parametrize("ruleset", [CURRENT_RULESET_VERSION, LEGACY_RULESET_VERSION])
@pytest.mark.parametrize("seed", [7, 19])
def test_public_trick_index_matches_engine_boundaries_through_game_over(ruleset, seed):
    state = make_initial_state(level=2, first_player=0, seed=seed, ruleset_version=ruleset)
    session = GameSession(difficulty=0, existing_state=state)
    rng = random.Random(seed)
    active = []
    completed = []
    for step in range(1000):
        before_history = len(state.history)
        before_trick = state.trick_number
        patterns = [find_complete_pattern([card], state.wild_card)
                    for card in state.hands[state.turn_index]]
        legal = [pattern for pattern in patterns if not state.table
                 or pattern.can_be_played_on(state.table[-1], level=state.level)]
        if state.table and (not legal or rng.random() < 0.25):
            pass_turn(state, state.turn_index)
        else:
            play_pattern(state, state.turn_index, rng.choice(legal))
        active.extend(event for event in state.history[before_history:]
                      if isinstance(event, (TurnPlayed, Pass)))
        if state.trick_number > before_trick:
            completed.append(active)
            active = []
        expected = {event.player: ("play", event.pattern) if isinstance(event, TurnPlayed)
                    else ("pass", None) for event in (active or completed[-1])}
        assert session.table_display_actions(preserve_completed_trick=True) == expected
        assert session.previous_completed_trick() == (completed[-1] if completed else [])
        if step % 9 == 0 or state.finished:
            assert _visible(state) == expected
        if state.finished:
            break
    assert state.finished


def test_fourway_geometry_for_all_perspectives_and_window_sizes():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    code = """
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication
from guandan.engine.card import Card, Suit
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.state import make_initial_state
from guandan.gui.theme import APP_QSS
from guandan.gui.window import GuandanMainWindow
from guandan.ui.session import GameSession

app = QApplication([])
app.setStyleSheet(APP_QSS)
window = GuandanMainWindow()
cards = tuple(Card(8, suit) for suit in
              (Suit.HEARTS, Suit.DIAMONDS, Suit.SPADES, Suit.CLUBS) for _ in range(2))
cards += (Card(2, Suit.HEARTS),) * 2
pattern = Pattern(PatternType.BOMB, 8, 10, cards, wild_used=2)
for human in range(4):
    state = make_initial_state(level=2, first_player=human, seed=7)
    session = GameSession(difficulty=0, existing_state=state, human=human)
    window.start_game(session)
    page = window.game_page
    page.deactivate()
    for size in ((1080, 760), (1280, 860)):
        window.resize(*size)
        window.show()
        for seat, area in page.table.play_areas.items():
            area.update_action(('play', pattern), is_top=seat == human, is_turn=seat == human)
        app.processEvents()
        assert (window.width(), window.height()) == size
        def rect(widget):
            return QRect(widget.mapTo(page.table, QPoint(0, 0)), widget.size())
        seats = session.visual_seats()
        seat_rects = {seat: rect(panel) for seat, panel in page.table.seat_panels.items()}
        play_rects = {seat: rect(area) for seat, area in page.table.play_areas.items()}
        assert play_rects[human].bottom() < seat_rects[human].top()
        assert play_rects[seats['opposite']].top() > seat_rects[seats['opposite']].bottom()
        assert play_rects[seats['left']].left() > seat_rects[seats['left']].right()
        assert play_rects[seats['right']].right() < seat_rects[seats['right']].left()
        rectangles = [*seat_rects.values(), *play_rects.values()]
        for i, region in enumerate(rectangles):
            assert page.table.rect().contains(region), (size, human, region)
            assert all(not region.intersects(other) for other in rectangles[i+1:])
        for area in page.table.play_areas.values():
            strip = area.cards
            assert len(strip._cards) == 10
            assert strip.width() >= 34 + 9 * 16
            assert area.rect().contains(QRect(strip.mapTo(area, QPoint(0, 0)), strip.size()))
        assert page.table.mapTo(window, QPoint(0, page.table.height())).y() < page.hand.mapTo(window, QPoint(0, 0)).y()
        page.table.show_activity()
        app.processEvents()
        assert page.table.activity_popup.isVisible()
        page.table.activity_popup.hide()
    session.game_saved = True
window.game_page = None
window.close()
app.quit()
"""
    result = subprocess.run([sys.executable, "-c", code],
                            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr

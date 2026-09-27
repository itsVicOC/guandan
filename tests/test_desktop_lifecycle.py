"""Exercise real Qt close/restart and lock contention in isolated processes."""
import os
import subprocess
import sys

import pytest


def run_desktop(code, tmp_path):
    pytest.importorskip("PySide6")
    result = subprocess.run(
        [sys.executable, "-c", code], text=True, capture_output=True, timeout=30,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "GUANDAN_DATA_DIR": str(tmp_path)},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_close_and_new_process_restore_pending_tribute(tmp_path):
    run_desktop('''
from unittest.mock import patch
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from guandan.gui.window import GuandanMainWindow
from guandan.ui.session import GameSession
from guandan.storage import load_game
from tests.test_reliability import finished_round
app = QApplication([])
state = finished_round()
session = GameSession(difficulty=0, existing_state=state, human=state.finish_order[0])
with patch("guandan.ui.session.random.randint", return_value=9):
    session.prepare_next_game()
session.begin_next_game_tribute()
assert session.pending_next_game_choice() is not None
window = GuandanMainWindow()
window.start_game(session)
window.show()
window.close()
for _ in range(500):
    if window._close_saved:
        break
    loop = QEventLoop()
    QTimer.singleShot(10, loop.quit)
    loop.exec()
assert window._close_saved
assert load_game()["pending_round"]["tribute_started"] is True
''', tmp_path)
    run_desktop('''
from PySide6.QtWidgets import QApplication
from guandan.gui.window import GuandanMainWindow
from guandan.storage import load_game
from guandan.ui.session import GameSession
app = QApplication([])
session = GameSession.from_savegame(load_game())
assert session.is_next_game_pending()
assert session.pending_next_game_choice() is not None
window = GuandanMainWindow()
window.start_game(session)
page = window.game_page
assert page.session.is_next_game_pending()
assert page._tribute_timer.isActive()
page.deactivate()
window.game_page = None
window.close()
''', tmp_path)


def test_leave_save_keeps_event_loop_responsive_while_storage_locked(tmp_path):
    run_desktop('''
import threading
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from guandan.storage.locking import storage_lock
from guandan.storage.paths import get_savegame_path
from guandan.engine.state import make_initial_state
from guandan.ui.session import GameSession
from guandan.gui.window import GuandanMainWindow
app = QApplication([])
window = GuandanMainWindow()
session = GameSession(difficulty=0, existing_state=make_initial_state(seed=9, first_player=0))
window.start_game(session)
locked, release = threading.Event(), threading.Event()
def hold_lock():
    with storage_lock(get_savegame_path()):
        locked.set()
        release.wait(3)
thread = threading.Thread(target=hold_lock)
thread.start()
assert locked.wait(1)
ticks = []
QTimer.singleShot(50, lambda: ticks.append(True))
QTimer.singleShot(150, release.set)
window.game_page.back_to_menu()
assert window.game_page._saving
for _ in range(500):
    if window._leave_worker is None:
        break
    loop = QEventLoop()
    QTimer.singleShot(10, loop.quit)
    loop.exec()
thread.join()
assert ticks and release.is_set()
assert window._leave_worker is None
assert window.game_page is None
window.close()
''', tmp_path)


def test_conflict_copy_allows_return_to_recovery_page(tmp_path):
    run_desktop('''
from unittest.mock import patch
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from guandan.engine.state import make_initial_state
from guandan.gui.window import GuandanMainWindow
from guandan.storage import load_game
from guandan.storage.savegame import list_recovery_games
from guandan.ui.session import GameSession
app = QApplication([])
owner = GameSession(difficulty=0, seed=9)
owner.save_unfinished()
session = GameSession(difficulty=0, existing_state=make_initial_state(seed=10, first_player=0))
window = GuandanMainWindow()
window.start_game(session)
with patch("guandan.gui.window.QMessageBox.warning") as warning:
    window.game_page.back_to_menu()
    for _ in range(500):
        if window._leave_worker is None:
            break
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()
    warning.assert_called_once()
assert window.game_page is None
assert load_game()["game_id"] == owner.game_id
assert session.game_id in {row["game_id"] for row in list_recovery_games()}
window.close()
''', tmp_path)

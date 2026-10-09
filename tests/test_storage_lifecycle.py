from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import threading
from unittest.mock import patch

import pytest

from guandan.tui.app import GuandanApp
from guandan.tui.screens.history import HistoryScreen
from guandan.tui.screens.load_save import LoadSaveScreen


@pytest.mark.parametrize("screen_class,patched", [
    (HistoryScreen, "guandan.tui.screens.history.load_history_list"),
    (LoadSaveScreen, "guandan.tui.screens.load_save.has_savegame"),
])
def test_tui_slow_read_keeps_back_responsive_and_discards_detached_error(screen_class, patched):
    started, release = threading.Event(), threading.Event()

    def blocked(*args, **kwargs):
        started.set()
        release.wait(3)
        raise OSError("late read failed")

    async def run():
        app = GuandanApp()
        with patch(patched, side_effect=blocked):
            async with app.run_test(size=(140, 48)) as pilot:
                screen = screen_class()
                app.push_screen(screen)
                await pilot.pause()
                try:
                    assert started.is_set() and screen._storage_busy
                    await pilot.press("escape")
                    await pilot.pause()
                    assert app.screen.__class__.__name__ == "MainMenuScreen"
                finally:
                    release.set()
                await pilot.pause()
                assert app.screen.__class__.__name__ == "MainMenuScreen"

    asyncio.run(run())


def test_gui_slow_read_keeps_event_loop_responsive_and_discards_detached_error():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    code = '''
import threading
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QThreadPool, QTimer
from guandan.gui.window import GuandanMainWindow
app = QApplication([])
window = GuandanMainWindow()
release = threading.Event()
started = threading.Event()
def blocked(*args, **kwargs):
    started.set()
    release.wait(3)
    raise OSError("late read failed")
with patch("guandan.gui.window.load_history_list", side_effect=blocked):
    window.show_history()
    history = window.stack.currentWidget()
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)
    loop = QEventLoop()
    QTimer.singleShot(100, loop.quit)
    loop.exec()
    assert started.is_set() and history._storage_busy and len(ticks) >= 2
    window.show_menu()
    menu = window.stack.currentWidget()
    release.set()
    assert QThreadPool.globalInstance().waitForDone(2000)
    app.processEvents()
    assert window.stack.currentWidget() is menu
    assert history._storage_completion is None
window.close()
app.quit()
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, timeout=15)
    assert result.returncode == 0, result.stderr

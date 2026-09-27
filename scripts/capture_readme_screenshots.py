"""Capture README images from a reproducible deal using the actual GUI/TUI."""
from __future__ import annotations

import argparse
import asyncio
import os
import random
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("GUANDAN_TUI_NO_RESIZE", "1")

from capture_visual_qa import _assert_png, _assert_svg
from PySide6.QtWidgets import QApplication

from guandan.ai import make_strategy, play_or_pass
from guandan.engine.replay import replay_events
from guandan.engine.state import GameState, make_initial_state
from guandan.gui.theme import APP_QSS
from guandan.gui.window import GuandanMainWindow
from guandan.tui.app import GuandanApp
from guandan.tui.screens.game import GameScreen
from guandan.ui.session import GameSession


def demo_state() -> GameState:
    """Advance a full, legal deal to the human's turn without editing any hand."""
    state = make_initial_state(level=5, first_player=0, seed=14)
    strategy = make_strategy(0)
    rng = random.Random(14)
    for action in range(100):
        play_or_pass(state, state.turn_index, strategy, rng)
        if action >= 3 and state.turn_index == 0 and not state.finished:
            # Verify that every card and action can be reconstructed by the engine.
            return replay_events(state.history)
        if state.finished:
            break
    raise RuntimeError("demo deal no longer reaches the expected human turn")


def capture_gui(output: Path, state: GameState) -> None:
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_QSS)
    window = GuandanMainWindow()
    window.resize(1280, 860)
    window.show()

    def capture(name: str) -> None:
        app.processEvents()
        target = output / f"{name}.png"
        if not window.grab().save(str(target)):
            raise RuntimeError(f"could not save {target}")
        _assert_png(target)

    capture("gui-lobby")
    window.start_game(GameSession(difficulty=0, existing_state=state, human=0))
    window.game_page.deactivate()
    window.game_page.organize_hand()
    capture("gui-table")
    window.show_replay({
        "played_at": "2026-09-27T12:00:00",
        "match_id": "readme-demo",
        "round_index": 1,
        "statistics": {},
        "events": state.history,
    })
    window.stack.currentWidget().set_event_index(len(state.history) - 1)
    capture("gui-replay")
    window.game_page = None
    window.close()
    app.processEvents()


async def capture_tui(output: Path, state: GameState) -> None:
    app = GuandanApp()
    async with app.run_test(size=(140, 48)) as pilot:
        await pilot.pause()
        screen = GameScreen(difficulty=0, existing_state=state, human=0)
        app.push_screen(screen)
        await pilot.pause()
        screen.action_organize_hand()
        await pilot.pause()
        app.save_screenshot("tui-table.svg", str(output))
    target = output / "tui-table.svg"
    target.write_text(
        "\n".join(line.rstrip() for line in target.read_text(encoding="utf-8").splitlines())
        + "\n",
        encoding="utf-8",
    )
    _assert_svg(target, ("你的手牌", "出牌", "理牌"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/images"))
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get("GUANDAN_DATA_DIR")
    # Documentation depicts the normal color UI, even in a colorless CI shell.
    previous_no_color = os.environ.pop("NO_COLOR", None)
    try:
        with TemporaryDirectory(prefix="guandan-readme-") as data_dir:
            os.environ["GUANDAN_DATA_DIR"] = data_dir
            state = demo_state()
            capture_gui(output, state)
            asyncio.run(capture_tui(output, state))
    finally:
        if previous is None:
            os.environ.pop("GUANDAN_DATA_DIR", None)
        else:
            os.environ["GUANDAN_DATA_DIR"] = previous
        if previous_no_color is not None:
            os.environ["NO_COLOR"] = previous_no_color
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Render deterministic GUI/TUI states and fail on blank or missing output."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("GUANDAN_TUI_NO_RESIZE", "1")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from guandan.engine.card import Card, Suit
from guandan.engine.rules.patterns import find_complete_pattern
from guandan.engine.state import make_initial_state, pass_turn, play_pattern
from guandan.gui.theme import APP_QSS
from guandan.gui.window import CardChoiceDialog, GuandanMainWindow
from guandan.tui.app import GuandanApp
from guandan.tui.screens.confirm import ConfirmModal, TributeChoiceModal
from guandan.tui.screens.error import ErrorModal
from guandan.tui.screens.game import GameScreen
from guandan.tui.screens.history import HistoryScreen
from guandan.tui.screens.replay import ReplayScreen
from guandan.ui.session import GameSession


def _assert_png(path: Path, width: int | None = None, height: int | None = None) -> dict:
    image = QImage(str(path))
    if image.isNull():
        raise RuntimeError(f"invalid PNG: {path}")
    if width is not None and image.width() != width:
        raise RuntimeError(f"unexpected PNG width: {path} ({image.width()} != {width})")
    if height is not None and image.height() != height:
        raise RuntimeError(f"unexpected PNG height: {path} ({image.height()} != {height})")
    colors = set()
    x_step = max(1, image.width() // 80)
    y_step = max(1, image.height() // 60)
    for y in range(0, image.height(), y_step):
        for x in range(0, image.width(), x_step):
            colors.add(image.pixelColor(x, y).rgba())
    if len(colors) < 8:
        raise RuntimeError(f"visually blank PNG: {path} ({len(colors)} sampled colors)")
    return {
        "path": str(path),
        "format": "png",
        "width": image.width(),
        "height": image.height(),
        "sampled_colors": len(colors),
    }


def _assert_svg(path: Path, required_text: tuple[str, ...]) -> dict:
    if path.stat().st_size < 1_000:
        raise RuntimeError(f"visually blank SVG: {path}")
    ET.parse(path)
    source = path.read_text(encoding="utf-8")
    missing = [text for text in required_text if text not in source]
    if missing:
        raise RuntimeError(f"SVG is missing expected text {missing}: {path}")
    return {
        "path": str(path),
        "format": "svg",
        "bytes": path.stat().st_size,
        "required_text": list(required_text),
    }


def _replay_history() -> dict:
    state = make_initial_state(level=2, first_player=0, seed=7)
    card = state.hands[0][0]
    pattern = find_complete_pattern([card], state.wild_card)
    if pattern is None:
        raise RuntimeError("visual replay seed did not produce a legal single")
    play_pattern(state, 0, pattern)
    pass_turn(state, 3)
    return {
        "played_at": "2026-07-27T12:00:00",
        "match_id": "visual-match",
        "round_index": 2,
        "statistics": {"actions": 2, "plays": 1, "passes": 1, "bombs": [0, 0]},
        "events": state.history,
    }


def capture_gui(output: Path) -> list[dict]:
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    if not isinstance(app, QApplication):
        raise RuntimeError("QApplication could not be created")
    app.setStyleSheet(APP_QSS)
    window = GuandanMainWindow()
    artifacts: list[dict] = []

    def capture(name: str, width: int, height: int) -> None:
        window.resize(width, height)
        window.show()
        app.processEvents()
        path = output / f"{name}-{width}x{height}.png"
        if not window.grab().save(str(path)):
            raise RuntimeError(f"could not save GUI screenshot: {path}")
        artifacts.append(_assert_png(path, width, height))

    for size in ((1280, 860), (1080, 760)):
        capture("menu", *size)

    state = make_initial_state(level=5, first_player=0, seed=14)
    state.hands[1] = state.hands[1][:1]
    state.hands[2] = state.hands[2][:7]
    state.hands[3] = state.hands[3][:2]
    window.start_game(GameSession(difficulty=0, existing_state=state, human=0))
    for size in ((1280, 860), (1080, 760)):
        capture("game-claims", *size)

    history = _replay_history()
    window.show_replay(history)
    replay = window.stack.currentWidget()
    replay.set_event_index(0)
    capture("replay-first", 1280, 860)
    replay.set_event_index(len(history["events"]) - 1)
    capture("replay-last", 1080, 760)

    with patch("guandan.gui.window.load_history_list", return_value=[]):
        window.show_history()
        capture("history-empty", 1080, 760)

    dialog = CardChoiceDialog(
        "return",
        tuple(Card(rank, Suit.HEARTS) for rank in range(3, 11)),
        window,
    )
    dialog.show()
    app.processEvents()
    dialog_path = output / "tribute-choice.png"
    if not dialog.grab().save(str(dialog_path)):
        raise RuntimeError(f"could not save GUI dialog screenshot: {dialog_path}")
    artifacts.append(_assert_png(dialog_path))
    dialog.close()
    window.game_page = None
    window.close()
    app.processEvents()
    return artifacts


async def _capture_tui_screen(output: Path, name: str, setup, required_text: tuple[str, ...]) -> dict:
    app = GuandanApp()
    async with app.run_test(size=(140, 48)) as pilot:
        await pilot.pause()
        await setup(app, pilot)
        await pilot.pause()
        app.save_screenshot(f"{name}.svg", str(output))
    return _assert_svg(output / f"{name}.svg", required_text)


async def capture_tui(output: Path) -> list[dict]:
    output.mkdir(parents=True, exist_ok=True)

    async def menu_setup(app, pilot) -> None:
        del app, pilot

    async def game_setup(app, pilot) -> None:
        del pilot
        state = make_initial_state(level=5, first_player=0, seed=14)
        state.hands[1] = state.hands[1][:1]
        state.hands[2] = state.hands[2][:7]
        state.hands[3] = state.hands[3][:2]
        app.push_screen(GameScreen(difficulty=0, existing_state=state, human=0))

    async def replay_setup(app, pilot) -> None:
        del pilot
        app.push_screen(ReplayScreen(_replay_history()))

    async def history_setup(app, pilot) -> None:
        with patch("guandan.tui.screens.history.load_history_list", return_value=[]):
            app.push_screen(HistoryScreen())
            await pilot.pause()

    async def tribute_setup(app, pilot) -> None:
        state = make_initial_state(level=5, first_player=0, seed=14)
        modal = TributeChoiceModal("return", state.hands[0][:10])
        app.push_screen(modal)
        await pilot.pause()
        if modal.query_one("#tribute-card-0").region.height <= 0:
            raise RuntimeError("tribute choice card is not visible")

    async def confirm_setup(app, pilot) -> None:
        del pilot
        app.push_screen(
            ConfirmModal(
                "删除存档",
                "确定删除当前存档？此操作不会删除历史战绩。",
                (("delete", "确认删除", "error"), ("cancel", "取消", "default")),
            )
        )

    async def error_setup(app, pilot) -> None:
        del pilot
        app.push_screen(ErrorModal("磁盘空间不足，牌局仍保留在当前页面。", title="保存失败"))

    specifications = (
        ("menu", menu_setup, ("掼蛋", "开始新局", "历史战绩")),
        ("game-claims", game_setup, ("你的手牌", "报单", "报双")),
        ("replay", replay_setup, ("对局回放", "四家手牌", "自动播放")),
        ("history-empty", history_setup, ("历史战绩", "暂无对局记录")),
        ("tribute-choice", tribute_setup, ("选择还贡牌", "取消")),
        ("confirm-delete", confirm_setup, ("删除存档", "确认删除", "取消")),
        ("error-save", error_setup, ("保存失败", "磁盘空间不足", "OK")),
    )
    artifacts = []
    for name, setup, required_text in specifications:
        artifacts.append(await _capture_tui_screen(output, name, setup, required_text))
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("visual-artifacts"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifacts = capture_gui(output / "gui")
    artifacts.extend(asyncio.run(capture_tui(output / "tui")))
    manifest = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "qt_platform": os.environ.get("QT_QPA_PLATFORM"),
        "artifacts": artifacts,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

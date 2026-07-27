"""断点续局屏。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from ...engine.state import SEAT_NAMES
from ...storage import has_savegame, load_game, restore_game_state


class LoadSaveScreen(Screen):
    """断点续局屏（加载/删除存档）。"""

    BINDINGS = [
        ("escape", "back", "返回"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)

        try:
            has_save = has_savegame()
            savegame = load_game() if has_save else None
        except OSError as exc:
            with Center(), Vertical(id="load-box"):
                yield Static("💾 断点续局", id="load-title")
                yield Static("无法读取存档", id="load-error")
                yield Static(str(exc), id="load-hint")
                yield Button("← 返回", id="btn-back")
            yield Footer()
            return

        if not has_save:
            with Center(), Vertical(id="load-box"):
                yield Static("💾 断点续局", id="load-title")
                yield Static("暂无存档", id="load-empty")
                yield Static("退出未完成的对局时会自动保存", id="load-hint")
                yield Button("← 返回", id="btn-back")
        else:
            if savegame:
                with Center(), Vertical(id="load-box"):
                    yield Static("💾 断点续局", id="load-title")
                    yield Static(f"存档时间：{savegame['saved_at'][:19]}")
                    metadata = savegame["metadata"]
                    snapshot = savegame["current_state_snapshot"]
                    yield Static(f"级牌：{metadata['level']} · 玩家：{SEAT_NAMES[metadata.get('player_seat', 0)]}")
                    yield Static(f"当前行动：{SEAT_NAMES[snapshot['turn_index']]}")
                    yield Static(f"AI 难度：{self._difficulty_text(metadata.get('ai_difficulties', []))}")
                    yield Static(f"已进行：{len(savegame['events'])} 步")
                    yield Static(f"手牌剩余：{self._hand_sizes_text(snapshot['hand_sizes'])}")
                    yield Button("继续游戏", id="btn-continue")
                    yield Button("删除存档", id="btn-delete", variant="error")
                    yield Button("← 返回", id="btn-back")
            else:
                with Center(), Vertical(id="load-box"):
                    yield Static("💾 断点续局", id="load-title")
                    yield Static("存档文件损坏", id="load-error")
                    yield Static("可以删除损坏存档后重新开始", id="load-hint")
                    yield Button("删除损坏存档", id="btn-delete", variant="error")
                    yield Button("← 返回", id="btn-back")

        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#load-title", Static).styles.text_style = "bold"
        self.query_one("#load-title", Static).styles.color = "yellow"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-continue":
            from .error import ErrorModal

            try:
                savegame = load_game()
            except OSError as exc:
                self.app.push_screen(ErrorModal(str(exc), title="无法读取存档"))
                return
            if not savegame:
                self.app.push_screen(ErrorModal("存档已不存在或无法解析。", title="无法继续存档"))
                return
            from .game import GameScreen

            try:
                state = restore_game_state(savegame)
            except ValueError as exc:
                self.app.push_screen(ErrorModal(str(exc), title="无法继续存档"))
                return
            metadata = savegame.get("metadata", {})
            ai_difficulties = metadata.get("ai_difficulties", [None, 2, 2, 2])
            difficulty = next((d for d in ai_difficulties if d is not None), 2)
            self.app.push_screen(
                GameScreen(
                    difficulty=difficulty,
                    level=metadata.get("level", state.level),
                    human=metadata.get("player_seat", 0),
                    existing_state=state,
                    game_id=savegame.get("game_id"),
                    match_id=savegame.get("match_id"),
                    round_index=savegame.get("round_index", 1),
                    elapsed_seconds=savegame.get("elapsed_seconds", 0),
                    seed=metadata.get("seed"),
                )
            )
        elif event.button.id == "btn-delete":
            from .confirm import ConfirmModal

            self.app.push_screen(
                ConfirmModal(
                    "删除存档",
                    "确定删除当前存档？此操作不会删除历史战绩。",
                    (("delete", "确认删除", "error"), ("cancel", "取消", "default")),
                ),
                self._resolve_delete,
            )
        else:
            self.app.pop_screen()

    def _resolve_delete(self, action: str | None) -> None:
        if action != "delete":
            return
        from ...storage import delete_savegame
        from .error import ErrorModal

        try:
            delete_savegame()
        except OSError as exc:
            self.app.push_screen(ErrorModal(str(exc), title="删除失败"))
            return
        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()

    def _hand_sizes_text(self, sizes: list[int]) -> str:
        return " / ".join(f"{SEAT_NAMES[i]} {size}" for i, size in enumerate(sizes))

    def _difficulty_text(self, ai_difficulties: list[object]) -> str:
        difficulty = next((d for d in ai_difficulties if d is not None), None)
        return str(difficulty) if difficulty is not None else "-"

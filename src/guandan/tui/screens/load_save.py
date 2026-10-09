"""断点续局屏。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.widgets import Button, Footer, Header, Static

from ...engine.state import SEAT_NAMES
from ...storage import has_savegame, load_game
from ...storage.savegame import activate_recovery, list_recovery_games
from ...ui.session import GameSession
from .storage_screen import StorageScreen


class LoadSaveScreen(StorageScreen):
    """断点续局屏（加载/删除存档）。"""

    BINDINGS = [
        ("escape", "back", "返回"),
    ]

    def __init__(self) -> None:
        super().__init__()
        # Identity of the save currently displayed, so deleting cannot remove a
        # save another process wrote after this screen was built.
        self._savegame_id: str | None = None
        self._savegame_revision: int | None = None
        self._loaded = False
        self._has_save = False
        self._savegame: dict | None = None
        self._recoveries: list[dict[str, str]] = []
        self._load_error = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)

        has_save, savegame = self._has_save, self._savegame
        if self._load_error:
            with Center(), Vertical(id="load-box"):
                yield Static("💾 断点续局", id="load-title")
                yield Static("无法读取存档", id="load-error")
                yield Static(self._load_error, id="load-hint")
                yield Button("← 返回", id="btn-back")
            yield Footer()
            return

        if not self._loaded:
            with Center(), Vertical(id="load-box"):
                yield Static("💾 断点续局", id="load-title")
                yield Static("读取存档中…", id="load-hint")
                yield Button("← 返回", id="btn-back")
        elif not has_save:
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

        for recovery in self._recoveries:
            yield Button(f"恢复副本 {recovery['saved_at'][:19]}（保留当前存档）",
                         id=f"recover-{recovery['name']}")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#load-title", Static).styles.text_style = "bold"
        self.query_one("#load-title", Static).styles.color = "yellow"
        self._reload()

    @staticmethod
    def _read_save() -> object:
        has_save = has_savegame()
        return has_save, load_game() if has_save else None, list_recovery_games()

    def _reload(self) -> None:
        self._start_storage(self._read_save, self._save_loaded)

    def on_screen_resume(self) -> None:
        if self.is_mounted:
            self._reload()

    def _save_loaded(self, payload: object) -> None:
        data, error = payload if isinstance(payload, tuple) else (None, ValueError("存档结果无效"))
        self._loaded = True
        self._load_error = str(error) if error else ""
        if data is not None:
            self._has_save, self._savegame, self._recoveries = data
            self._savegame_id = self._savegame.get("game_id") if self._savegame else None
            self._savegame_revision = self._savegame.get("revision", 0) if self._savegame else None
        self.refresh(recompose=True)

    def _operation_finished(self, payload: object) -> None:
        _, error = payload if isinstance(payload, tuple) else (None, ValueError("存档结果无效"))
        if error:
            from .error import ErrorModal
            self.app.push_screen(ErrorModal(str(error), title="存档操作失败"))
        else:
            self._reload()

    @staticmethod
    def _restore_session() -> GameSession:
        savegame = load_game()
        if not savegame:
            raise ValueError("存档已不存在或无法解析。")
        return GameSession.from_savegame(savegame)

    def _continued(self, payload: object) -> None:
        session, error = payload if isinstance(payload, tuple) else (None, ValueError("存档结果无效"))
        if error:
            from .error import ErrorModal
            self.app.push_screen(ErrorModal(str(error), title="无法继续存档"))
        else:
            from .game import GameScreen
            self.app.push_screen(GameScreen(session=session))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
            return
        if self._storage_busy:
            return
        if event.button.id and event.button.id.startswith("recover-"):
            name = event.button.id.removeprefix("recover-")
            self._start_storage(lambda: activate_recovery(name), self._operation_finished)
        elif event.button.id == "btn-continue":
            self._start_storage(self._restore_session, self._continued)
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
        game_id, revision = self._savegame_id, self._savegame_revision
        self._start_storage(lambda: delete_savegame(expected_game_id=game_id,
                                                   expected_revision=revision), self._deleted)

    def _deleted(self, payload: object) -> None:
        _, error = payload if isinstance(payload, tuple) else (None, ValueError("存档结果无效"))
        if error:
            from .error import ErrorModal
            self.app.push_screen(ErrorModal(str(error), title="删除失败"))
        else:
            self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()

    def _hand_sizes_text(self, sizes: list[int]) -> str:
        return " / ".join(f"{SEAT_NAMES[i]} {size}" for i, size in enumerate(sizes))

    def _difficulty_text(self, ai_difficulties: list[object]) -> str:
        difficulty = next((d for d in ai_difficulties if d is not None), None)
        return str(difficulty) if difficulty is not None else "-"

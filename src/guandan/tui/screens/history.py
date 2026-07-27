"""历史战绩屏。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

from ...storage import load_history_detail, load_history_list
from ...ui.history import HISTORY_COLUMNS, history_entry_cells
from .error import ErrorModal


class HistoryScreen(Screen):
    """历史战绩屏（显示最近对局记录）。"""

    CSS = """
    HistoryScreen {
        align: center middle;
        background: #101512;
        color: #eee8d9;
    }
    #hist-box {
        width: 72;
        height: 18;
        padding: 2 4;
        border: round #d6b35a;
        background: #18211d;
        align: center middle;
    }
    #hist-title, #hist-empty, #hist-hint, #hist-subtitle {
        width: 100%;
        text-align: center;
        margin-bottom: 1;
    }
    #hist-title { color: #ffd978; text-style: bold; }
    #hist-empty { color: #eee8d9; }
    #hist-hint, #hist-subtitle { color: #9fb7a6; }
    #hist-scroll {
        width: 96%;
        height: 1fr;
        padding: 1 2;
    }
    #hist-table { height: 1fr; }
    #btn-replay, #btn-back { width: 28; margin: 1; }
    """

    BINDINGS = [
        ("r", "replay", "查看回放"),
        ("escape", "back", "返回"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._history: list[dict] = []
        self._history_error = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)

        try:
            self._history = load_history_list(limit=20)
        except OSError as exc:
            self._history_error = str(exc)
            self._history = []

        if self._history_error:
            with Center(), Vertical(id="hist-box"):
                yield Static("📊 历史战绩", id="hist-title")
                yield Static("无法读取历史记录", id="hist-empty")
                yield Static(self._history_error, id="hist-hint")
                yield Button("← 返回", id="btn-back")
        elif not self._history:
            with Center(), Vertical(id="hist-box"):
                yield Static("📊 历史战绩", id="hist-title")
                yield Static("暂无对局记录", id="hist-empty")
                yield Static("完成一局后记录将显示在这里", id="hist-hint")
                yield Button("← 返回", id="btn-back")
        else:
            with VerticalScroll(id="hist-scroll"):
                yield Static("📊 历史战绩", id="hist-title")
                match_count = len(
                    {
                        entry.get("match_id")
                        for entry in self._history
                        if entry.get("match_id")
                    }
                )
                yield Static(
                    f"{match_count} 场比赛 · 最近 {len(self._history)} 局记录",
                    id="hist-subtitle",
                )
                yield DataTable(id="hist-table")
            with Center():
                yield Button("R  查看回放", id="btn-replay", variant="primary")
                yield Button("← 返回", id="btn-back")

        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#hist-title", Static).styles.text_style = "bold"
        self.query_one("#hist-title", Static).styles.color = "yellow"
        tables = list(self.query(DataTable))
        if tables:
            table = tables[0]
            table.add_columns(*HISTORY_COLUMNS)
            for entry in self._history:
                table.add_row(*self._entry_cells(entry))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-replay":
            self.action_replay()
        else:
            self.app.pop_screen()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.action_replay()

    def action_replay(self) -> None:
        if not self._history:
            self.app.push_screen(ErrorModal("暂无可查看的历史战绩。"))
            return
        table = self.query_one("#hist-table", DataTable)
        row = table.cursor_row
        if not 0 <= row < len(self._history):
            self.app.push_screen(ErrorModal("请先选择一局历史战绩。"))
            return
        try:
            detail = load_history_detail(self._history[row]["game_id"])
        except OSError as exc:
            self.app.push_screen(ErrorModal(str(exc), title="无法读取回放"))
            return
        if detail is None:
            self.app.push_screen(ErrorModal("这局历史记录无法读取。", title="无法读取回放"))
            return
        from .replay import ReplayScreen

        try:
            self.app.push_screen(ReplayScreen(detail))
        except ValueError as exc:
            self.app.push_screen(ErrorModal(str(exc), title="回放数据无效"))

    def action_back(self) -> None:
        self.app.pop_screen()

    def _entry_cells(self, entry: dict) -> tuple[str, ...]:
        """格式化历史记录表格行。

        Args:
            entry: 历史记录元数据

        Returns:
            时间、名次、难度、时长、标记。
        """

        return history_entry_cells(entry)

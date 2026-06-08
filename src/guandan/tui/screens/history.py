"""历史战绩屏。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

from ...storage import load_history_list


class HistoryScreen(Screen):
    """历史战绩屏（显示最近对局记录）。"""

    BINDINGS = [
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
                yield Static(f"最近 {len(self._history)} 场对局", id="hist-subtitle")
                yield DataTable(id="hist-table")
            with Center():
                yield Button("← 返回", id="btn-back")

        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#hist-title", Static).styles.text_style = "bold"
        self.query_one("#hist-title", Static).styles.color = "yellow"
        tables = list(self.query(DataTable))
        if tables:
            table = tables[0]
            table.add_columns("时间", "名次", "难度", "时长", "标记")
            for entry in self._history:
                table.add_row(*self._entry_cells(entry))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()

    def _entry_cells(self, entry: dict) -> tuple[str, str, str, str, str]:
        """格式化历史记录表格行。

        Args:
            entry: 历史记录元数据

        Returns:
            时间、名次、难度、时长、标记。
        """

        played_at = entry["played_at"][:19]  # 去掉毫秒
        result = entry["result"]
        rank = result["player_rank"]
        rank_names = ["上游", "二游", "三游", "下游"]
        rank_text = rank_names[rank - 1]

        ai_diffs = entry["metadata"]["ai_difficulties"]
        ai_diff = next((d for d in ai_diffs if d is not None), 2)

        duration = entry["duration_seconds"]
        duration_min = duration // 60
        duration_sec = duration % 60

        marks = []
        if result["drift"]:
            marks.append("漂")
        if result["guo_a"]:
            marks.append("过A")

        return (
            played_at,
            rank_text,
            str(ai_diff),
            f"{duration_min}:{duration_sec:02d}",
            " / ".join(marks) or "-",
        )

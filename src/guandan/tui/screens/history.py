"""历史战绩屏。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from ...storage import load_history_list


class HistoryScreen(Screen):
    """历史战绩屏（显示最近对局记录）。"""

    BINDINGS = [
        ("escape", "back", "返回"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)

        # 加载历史记录
        history = load_history_list(limit=20)

        if not history:
            with Center(), Vertical(id="hist-box"):
                yield Static("📊 历史战绩", id="hist-title")
                yield Static("暂无对局记录", id="hist-empty")
                yield Static("完成一局后记录将显示在这里", id="hist-hint")
                yield Button("← 返回", id="btn-back")
        else:
            with VerticalScroll(id="hist-scroll"):
                yield Static("📊 历史战绩", id="hist-title")
                yield Static(f"最近 {len(history)} 场对局", id="hist-subtitle")
                for entry in history:
                    yield Static(self._format_entry(entry), classes="hist-entry")
            with Center():
                yield Button("← 返回", id="btn-back")

        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#hist-title", Static).styles.text_style = "bold"
        self.query_one("#hist-title", Static).styles.color = "yellow"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()

    def _format_entry(self, entry: dict) -> str:
        """格式化历史记录条目。

        Args:
            entry: 历史记录元数据

        Returns:
            格式化字符串
        """
        # 提取信息
        played_at = entry["played_at"][:19]  # 去掉毫秒
        result = entry["result"]
        rank = result["player_rank"]
        rank_names = ["上游", "二游", "三游", "下游"]
        rank_text = rank_names[rank - 1]

        # AI 难度
        ai_diffs = entry["metadata"]["ai_difficulties"]
        # 找第一个非 None 的难度
        ai_diff = next((d for d in ai_diffs if d is not None), 2)

        # 时长
        duration = entry["duration_seconds"]
        duration_min = duration // 60
        duration_sec = duration % 60

        # 漂牌/过A标记
        drift_mark = " 🚀漂" if result["drift"] else ""
        guo_a_mark = " 🅰️过A" if result["guo_a"] else ""

        return f"{played_at} | {rank_text} | 难度{ai_diff} | {duration_min}:{duration_sec:02d}{drift_mark}{guo_a_mark}"

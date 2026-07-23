"""Shared history-list and replay metadata formatting."""
from __future__ import annotations

from typing import Any

HISTORY_COLUMNS = ("时间", "名次", "难度", "时长", "行动", "炸弹", "标记")


def history_entry_cells(entry: dict[str, Any]) -> tuple[str, ...]:
    result = entry.get("result", {})
    rank_names = ["上游", "二游", "三游", "下游"]
    player_rank = result.get("player_rank")
    rank = rank_names[player_rank - 1] if player_rank in range(1, 5) else "-"
    metadata = entry.get("metadata", {})
    ai_difficulties = metadata.get("ai_difficulties", [])
    ai_difficulty = next((item for item in ai_difficulties if item is not None), "-")
    duration = entry.get("duration_seconds", 0)
    duration = duration if isinstance(duration, int) and duration >= 0 else 0
    statistics = entry.get("statistics", {})
    actions = statistics.get("actions", "-")
    bombs = statistics.get("bombs", [])
    bomb_text = "/".join(str(item) for item in bombs) if len(bombs) == 2 else "-"
    marks = []
    if result.get("guo_a"):
        marks.append("过 A")
    if statistics.get("tribute_resisted"):
        marks.append("抗贡")
    return (
        str(entry.get("played_at", "-"))[:19],
        rank,
        str(ai_difficulty),
        f"{duration // 60}:{duration % 60:02d}",
        str(actions),
        bomb_text,
        " / ".join(marks) or "-",
    )


def history_statistics_text(entry: dict[str, Any]) -> str:
    statistics = entry.get("statistics", {})
    if not statistics:
        return "历史统计不可用"
    raw_bombs = statistics.get("bombs", [0, 0])
    bombs = raw_bombs if isinstance(raw_bombs, (list, tuple)) and len(raw_bombs) >= 2 else [0, 0]
    return (
        f"行动 {statistics.get('actions', 0)} · "
        f"出牌 {statistics.get('plays', 0)} · 过牌 {statistics.get('passes', 0)} · "
        f"报牌 {statistics.get('claims', 0)} · 进贡 {statistics.get('tributes', 0)} · "
        f"炸弹 东西 {bombs[0]} / 南北 {bombs[1]}"
    )


__all__ = ["HISTORY_COLUMNS", "history_entry_cells", "history_statistics_text"]

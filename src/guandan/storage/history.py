"""历史记录管理：对局回放和统计。

历史记录包含：
- 完整事件流（支持回放）
- 对局结果（快速查询）
- 元数据（玩家座位、AI 难度、时长）
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from ..engine.events import GameOver
from ..engine.state import GameState
from .paths import get_history_dir
from .serialization import deserialize_events, serialize_events


def save_history(
    state: GameState,
    game_id: str,
    player_seat: int,
    ai_difficulties: list[Optional[int]],
    seed: int,
    duration_seconds: int,
) -> None:
    """保存历史记录（对局结束后调用）。

    Args:
        state: 游戏状态
        game_id: 对局 ID
        player_seat: 玩家座位（0-3）
        ai_difficulties: AI 难度列表
        seed: 随机种子
        duration_seconds: 对局时长（秒）

    Raises:
        ValueError: 未找到 GameOver 事件
    """
    # 提取结果
    game_over_event = None
    for ev in reversed(state.history):
        if isinstance(ev, GameOver):
            game_over_event = ev
            break

    if not game_over_event:
        raise ValueError("No GameOver event found in history")

    # 玩家名次
    player_rank = game_over_event.finish_order.index(player_seat) + 1

    data = {
        "version": "1.0",
        "game_id": game_id,
        "played_at": datetime.now().isoformat(),
        "duration_seconds": duration_seconds,
        "metadata": {
            "level": state.level,
            "player_seat": player_seat,
            "ai_difficulties": ai_difficulties,
            "seed": seed,
        },
        "result": {
            "finish_order": list(game_over_event.finish_order),
            "final_levels": list(game_over_event.team_levels),
            "drift": game_over_event.drift,
            "guo_a": game_over_event.guo_a,
            "winner_team": game_over_event.winner_team,
            "player_rank": player_rank,
        },
        "events": serialize_events(state.history),
    }

    # 文件名：时间戳_game_id.json
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"{timestamp}_{game_id}.json"
    path = get_history_dir() / filename

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_history_list(limit: int = 20) -> list[dict[str, Any]]:
    """加载历史记录列表（仅元数据，不含完整事件流）。

    Args:
        limit: 最多返回多少条记录（默认 20）

    Returns:
        按时间倒序排列的历史记录列表
    """
    history_dir = get_history_dir()
    files = sorted(history_dir.glob("*.json"), reverse=True)

    result = []
    for file_path in files[:limit]:
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            # 只保留元数据，不加载完整事件流（节省内存）
            result.append(
                {
                    "game_id": data["game_id"],
                    "played_at": data["played_at"],
                    "duration_seconds": data["duration_seconds"],
                    "result": data["result"],
                    "metadata": data["metadata"],
                    "file_path": str(file_path),
                }
            )
        except (OSError, json.JSONDecodeError, KeyError):
            # 跳过损坏的文件
            continue

    return result


def load_history_detail(game_id: str) -> Optional[dict[str, Any]]:
    """加载完整历史记录（含事件流，用于回放）。

    Args:
        game_id: 对局 ID

    Returns:
        完整历史记录（包含反序列化的事件流），未找到时返回 None
    """
    history_dir = get_history_dir()

    # 查找匹配的文件（文件名包含 game_id）
    for file_path in history_dir.glob(f"*_{game_id}.json"):
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            # 反序列化事件流
            data["events"] = deserialize_events(data["events"])

            return data
        except (OSError, json.JSONDecodeError, ValueError):
            # 跳过损坏的文件
            continue

    return None


__all__ = [
    "load_history_detail",
    "load_history_list",
    "save_history",
]

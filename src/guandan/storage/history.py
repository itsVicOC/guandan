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

from ..engine.events import (
    Claim,
    GameOver,
    Pass,
    TributeResisted,
    TributeSent,
    TurnPlayed,
)
from ..engine.state import GameState
from .jsonio import write_json_atomic
from .locking import storage_lock
from .paths import get_history_dir, validate_game_id
from .serialization import deserialize_events, serialize_events


def save_history(
    state: GameState,
    game_id: str,
    player_seat: int,
    ai_difficulties: list[Optional[int]],
    seed: int,
    duration_seconds: int,
    match_id: str | None = None,
    round_index: int = 1,
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
    game_id = validate_game_id(game_id)
    resolved_match_id = validate_game_id(match_id or game_id)
    if round_index < 1:
        raise ValueError("round_index must be positive")

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

    history_dir = get_history_dir()
    with storage_lock(history_dir):
        existing_paths = list(history_dir.glob(f"*_{game_id}.json"))
        existing_path = existing_paths[0] if existing_paths else None
        played_at = datetime.now().isoformat()
        if existing_path is not None:
            try:
                with open(existing_path, encoding="utf-8") as stream:
                    existing_data = json.load(stream)
                if isinstance(existing_data, dict) and isinstance(
                    existing_data.get("played_at"), str
                ):
                    played_at = existing_data["played_at"]
            except (OSError, TypeError, ValueError):
                pass

        data = {
            "version": "1.0",
            "game_id": game_id,
            "match_id": resolved_match_id,
            "round_index": round_index,
            "played_at": played_at,
            "duration_seconds": duration_seconds,
            "metadata": {
                "level": state.level,
                "player_seat": player_seat,
                "ai_difficulties": ai_difficulties,
                "seed": seed,
                "match_id": resolved_match_id,
                "round_index": round_index,
            },
            "result": {
                "finish_order": list(game_over_event.finish_order),
                "final_levels": list(game_over_event.team_levels),
                "drift": game_over_event.drift,
                "guo_a": game_over_event.guo_a,
                "winner_team": game_over_event.winner_team,
                "player_rank": player_rank,
            },
            "statistics": _history_statistics(state),
            "events": serialize_events(state.history),
        }

        # 文件名：时间戳_game_id.json
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"{timestamp}_{game_id}.json"
        path = existing_path or history_dir / filename
        write_json_atomic(path, data)


def load_history_list(limit: int = 20) -> list[dict[str, Any]]:
    """加载历史记录列表（仅元数据，不含完整事件流）。

    Args:
        limit: 最多返回多少条记录（默认 20）

    Returns:
        按时间倒序排列的历史记录列表
    """
    history_dir = get_history_dir()
    files = sorted(history_dir.glob("*.json"), reverse=True)

    result: list[dict[str, Any]] = []
    for file_path in files:
        if len(result) >= limit:
            break
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            # 只保留元数据，不加载完整事件流（节省内存）
            result.append(
                {
                    "game_id": data["game_id"],
                    "match_id": data.get(
                        "match_id",
                        data.get("metadata", {}).get("match_id", data["game_id"]),
                    ),
                    "round_index": data.get(
                        "round_index", data.get("metadata", {}).get("round_index", 1)
                    ),
                    "played_at": data["played_at"],
                    "duration_seconds": data["duration_seconds"],
                    "result": data["result"],
                    "metadata": data["metadata"],
                    "statistics": data.get("statistics", {}),
                    "file_path": str(file_path),
                }
            )
        except (KeyError, OSError, TypeError, ValueError):
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
    try:
        game_id = validate_game_id(game_id)
    except ValueError:
        return None
    history_dir = get_history_dir()

    # 查找匹配的文件（文件名包含 game_id）
    for file_path in history_dir.glob(f"*_{game_id}.json"):
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("history must be an object")

            # 反序列化事件流
            data["events"] = deserialize_events(data["events"])

            return data
        except (KeyError, OSError, TypeError, ValueError):
            # 跳过损坏的文件
            continue

    return None


def _history_statistics(state: GameState) -> dict[str, Any]:
    plays = sum(isinstance(event, TurnPlayed) for event in state.history)
    passes = sum(isinstance(event, Pass) for event in state.history)
    return {
        "actions": plays + passes,
        "plays": plays,
        "passes": passes,
        "claims": sum(isinstance(event, Claim) for event in state.history),
        "tributes": sum(isinstance(event, TributeSent) for event in state.history),
        "tribute_resisted": any(
            isinstance(event, TributeResisted) for event in state.history
        ),
        "bombs": list(state.team_bomb_count),
        "event_count": len(state.history),
    }


__all__ = [
    "load_history_detail",
    "load_history_list",
    "save_history",
]

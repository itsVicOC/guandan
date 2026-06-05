"""游戏存档管理：断点续局。

存档包含：
- 完整事件流（可重建状态）
- 当前状态快照（快速显示）
- 元数据（玩家座位、AI 难度、种子）
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from ..engine.state import GameState
from .paths import get_savegame_path
from .serialization import deserialize_events, serialize_events


def save_game(
    state: GameState,
    game_id: str,
    player_seat: int,
    ai_difficulties: list[Optional[int]],
    seed: int,
) -> None:
    """保存当前对局。

    Args:
        state: 当前游戏状态
        game_id: 对局 ID
        player_seat: 玩家座位（0-3）
        ai_difficulties: 4 个座位的 AI 难度（玩家位置为 None）
        seed: 随机种子
    """
    data = {
        "version": "1.0",
        "saved_at": datetime.now().isoformat(),
        "game_id": game_id,
        "metadata": {
            "level": state.level,
            "player_seat": player_seat,
            "ai_difficulties": ai_difficulties,
            "seed": seed,
        },
        "events": serialize_events(state.history),
        "current_state_snapshot": {
            "turn_index": state.turn_index,
            "finish_order": list(state.finish_order),
            "hand_sizes": [len(h) for h in state.hands],
            "finished": state.finished,
        },
    }

    path = get_savegame_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_game() -> Optional[dict[str, Any]]:
    """加载存档。

    Returns:
        存档数据（包含反序列化的事件流），无存档时返回 None
    """
    path = get_savegame_path()
    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 反序列化事件流
        data["events"] = deserialize_events(data["events"])

        return data
    except (json.JSONDecodeError, IOError, ValueError):
        # 文件损坏
        return None


def delete_savegame() -> None:
    """删除存档（对局结束后调用）。"""
    path = get_savegame_path()
    if path.exists():
        path.unlink()


def has_savegame() -> bool:
    """是否存在存档。

    Returns:
        True 表示有存档
    """
    return get_savegame_path().exists()


__all__ = [
    "save_game",
    "load_game",
    "delete_savegame",
    "has_savegame",
]

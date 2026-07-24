"""用户配置和统计管理。

Profile 包含：
- 用户偏好（默认难度、提示开关）
- 统计数据（总局数、胜率、分档位统计）
"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any

from .jsonio import write_json_atomic
from .paths import get_profile_path

PROFILE_VERSION = "2.0"

# 默认配置
DEFAULT_PROFILE: dict[str, Any] = {
    "version": PROFILE_VERSION,
    "player_name": "玩家",
    "preferences": {
        "default_difficulty": 2,
        "show_hints": True,
    },
    "statistics": {
        "total_games": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "by_difficulty": {},
        "recorded_game_ids": [],
    },
    "created_at": None,
    "updated_at": None,
}


def load_profile() -> dict[str, Any]:
    """加载用户配置。

    不存在时返回默认值。

    Returns:
        用户配置字典
    """
    path = get_profile_path()
    if not path.exists():
        return copy.deepcopy(DEFAULT_PROFILE)

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return _migrate_profile(data)
    except (OSError, TypeError, ValueError):
        # 文件损坏，返回默认值
        return copy.deepcopy(DEFAULT_PROFILE)


def save_profile(profile: dict[str, Any]) -> None:
    """保存用户配置。

    Args:
        profile: 用户配置字典
    """
    profile["updated_at"] = datetime.now().isoformat()
    if not profile.get("created_at"):
        profile["created_at"] = profile["updated_at"]

    path = get_profile_path()
    profile["version"] = PROFILE_VERSION
    write_json_atomic(path, profile)


def update_statistics(
    profile: dict[str, Any],
    *,
    won: bool,
    difficulty: int,
    game_id: str | None = None,
) -> bool:
    """更新统计数据（对局结束后调用）。

    Args:
        profile: 用户配置
        won: 真人所在搭档队伍是否取得头游
        difficulty: AI 难度（0-4）
    """
    stats = profile["statistics"]
    recorded_game_ids = stats.setdefault("recorded_game_ids", [])
    if game_id is not None and game_id in recorded_game_ids:
        return False

    # 总对局数
    stats["total_games"] += 1

    if won:
        stats["wins"] += 1
    else:
        stats["losses"] += 1

    # 胜率
    if stats["total_games"] > 0:
        stats["win_rate"] = stats["wins"] / stats["total_games"]

    # 分难度统计
    diff_key = str(difficulty)
    if diff_key not in stats["by_difficulty"]:
        stats["by_difficulty"][diff_key] = {"games": 0, "wins": 0}

    stats["by_difficulty"][diff_key]["games"] += 1
    if won:
        stats["by_difficulty"][diff_key]["wins"] += 1
    if game_id is not None:
        recorded_game_ids.append(game_id)
    return True


def _migrate_profile(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("profile must be an object")
    profile = copy.deepcopy(DEFAULT_PROFILE)
    if isinstance(data.get("player_name"), str):
        profile["player_name"] = data["player_name"]
    if isinstance(data.get("preferences"), dict):
        profile["preferences"].update(data["preferences"])
    if isinstance(data.get("statistics"), dict):
        profile["statistics"].update(data["statistics"])
    recorded = profile["statistics"].get("recorded_game_ids", [])
    profile["statistics"]["recorded_game_ids"] = (
        [item for item in recorded if isinstance(item, str)]
        if isinstance(recorded, list)
        else []
    )
    profile["created_at"] = data.get("created_at")
    profile["updated_at"] = data.get("updated_at")
    profile["version"] = PROFILE_VERSION
    return profile


__all__ = [
    "DEFAULT_PROFILE",
    "PROFILE_VERSION",
    "load_profile",
    "save_profile",
    "update_statistics",
]

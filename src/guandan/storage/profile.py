"""用户配置和统计管理。

Profile 包含：
- 用户偏好（默认难度、提示开关）
- 统计数据（总局数、胜率、分档位统计）
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .paths import get_profile_path

# 默认配置
DEFAULT_PROFILE: dict[str, Any] = {
    "version": "1.0",
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
        profile = DEFAULT_PROFILE.copy()
        profile["preferences"] = DEFAULT_PROFILE["preferences"].copy()
        profile["statistics"] = DEFAULT_PROFILE["statistics"].copy()
        profile["statistics"]["by_difficulty"] = {}
        return profile

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        # 文件损坏，返回默认值
        return DEFAULT_PROFILE.copy()


def save_profile(profile: dict[str, Any]) -> None:
    """保存用户配置。

    Args:
        profile: 用户配置字典
    """
    profile["updated_at"] = datetime.now().isoformat()
    if not profile.get("created_at"):
        profile["created_at"] = profile["updated_at"]

    path = get_profile_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)


def update_statistics(profile: dict[str, Any], player_rank: int, difficulty: int) -> None:
    """更新统计数据（对局结束后调用）。

    Args:
        profile: 用户配置
        player_rank: 玩家名次（1=上游，2=二游，3=三游，4=下游）
        difficulty: AI 难度（0-4）
    """
    stats = profile["statistics"]

    # 总对局数
    stats["total_games"] += 1

    # 胜负（上游/二游算赢，三游/下游算输）
    if player_rank <= 2:
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
    if player_rank <= 2:
        stats["by_difficulty"][diff_key]["wins"] += 1


__all__ = [
    "DEFAULT_PROFILE",
    "load_profile",
    "save_profile",
    "update_statistics",
]

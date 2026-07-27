"""用户配置和统计管理。

Profile 包含：
- 用户偏好（默认难度、提示开关）
- 小局头游统计与成功过 A 后的整场比赛胜负统计
"""
from __future__ import annotations

import copy
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from .jsonio import write_json_atomic
from .locking import storage_lock
from .paths import get_profile_path

PROFILE_VERSION = "3.0"
_ResultT = TypeVar("_ResultT")

# 默认配置
DEFAULT_PROFILE: dict[str, Any] = {
    "version": PROFILE_VERSION,
    "player_name": "玩家",
    "preferences": {
        "default_difficulty": 2,
        "show_hints": True,
    },
    "statistics": {
        "total_rounds": 0,
        "head_rounds": 0,
        "head_rate": 0.0,
        "by_difficulty_rounds": {},
        "by_difficulty": {},
        "recorded_game_ids": [],
        "total_matches": 0,
        "match_wins": 0,
        "match_losses": 0,
        "match_win_rate": 0.0,
        "recorded_match_ids": [],
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
    with storage_lock(path):
        return _load_profile_unlocked(path)


def _load_profile_unlocked(path: Path) -> dict[str, Any]:
    if not path.exists():
        return copy.deepcopy(DEFAULT_PROFILE)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return _migrate_profile(data)
    except FileNotFoundError:
        return copy.deepcopy(DEFAULT_PROFILE)
    except (KeyError, TypeError, ValueError):
        # 文件损坏，返回默认值
        return copy.deepcopy(DEFAULT_PROFILE)


def save_profile(profile: dict[str, Any]) -> None:
    """保存用户配置。

    Args:
        profile: 用户配置字典
    """
    path = get_profile_path()
    with storage_lock(path):
        _save_profile_unlocked(path, profile)


def _save_profile_unlocked(path: Path, profile: dict[str, Any]) -> None:
    profile["updated_at"] = datetime.now().isoformat()
    if not profile.get("created_at"):
        profile["created_at"] = profile["updated_at"]
    profile["version"] = PROFILE_VERSION
    write_json_atomic(path, profile)


def update_profile(mutator: Callable[[dict[str, Any]], _ResultT]) -> _ResultT:
    """Apply one read-modify-write transaction without losing concurrent updates."""
    path = get_profile_path()
    with storage_lock(path):
        profile = _load_profile_unlocked(path)
        result = mutator(profile)
        _save_profile_unlocked(path, profile)
        return result


def record_round_statistics(
    profile: dict[str, Any],
    *,
    got_head: bool,
    difficulty: int,
    game_id: str | None = None,
) -> bool:
    """Record one completed round without presenting it as a match win."""
    stats = profile["statistics"]
    recorded_game_ids = stats.setdefault("recorded_game_ids", [])
    if game_id is not None and game_id in recorded_game_ids:
        return False

    stats["total_rounds"] = int(stats.get("total_rounds", stats.get("total_games", 0))) + 1
    stats.setdefault("head_rounds", int(stats.get("wins", 0)))
    if got_head:
        stats["head_rounds"] += 1
    stats["head_rate"] = stats["head_rounds"] / stats["total_rounds"]

    diff_key = str(difficulty)
    by_round = stats.setdefault("by_difficulty_rounds", {})
    if diff_key not in by_round:
        by_round[diff_key] = {"rounds": 0, "heads": 0}
    by_round[diff_key]["rounds"] += 1
    if got_head:
        by_round[diff_key]["heads"] += 1
    if game_id is not None:
        recorded_game_ids.append(game_id)
    return True


def record_match_statistics(
    profile: dict[str, Any],
    *,
    won: bool,
    difficulty: int,
    match_id: str | None = None,
) -> bool:
    """Record a match only after one team has successfully passed A."""
    stats = profile["statistics"]
    recorded_match_ids = stats.setdefault("recorded_match_ids", [])
    if match_id is not None and match_id in recorded_match_ids:
        return False

    stats["total_matches"] = int(stats.get("total_matches", 0)) + 1
    stats.setdefault("match_wins", 0)
    stats.setdefault("match_losses", 0)
    if won:
        stats["match_wins"] += 1
    else:
        stats["match_losses"] += 1
    stats["match_win_rate"] = stats["match_wins"] / stats["total_matches"]

    diff_key = str(difficulty)
    by_difficulty = stats.setdefault("by_difficulty", {})
    if diff_key not in by_difficulty:
        by_difficulty[diff_key] = {"matches": 0, "wins": 0}
    by_difficulty[diff_key].setdefault("matches", 0)
    by_difficulty[diff_key].setdefault("wins", 0)
    by_difficulty[diff_key]["matches"] += 1
    if won:
        by_difficulty[diff_key]["wins"] += 1
    if match_id is not None:
        recorded_match_ids.append(match_id)
    return True


def update_statistics(
    profile: dict[str, Any],
    *,
    won: bool,
    difficulty: int,
    game_id: str | None = None,
) -> bool:
    """Compatibility wrapper for callers that still record round head results."""
    return record_round_statistics(
        profile,
        got_head=won,
        difficulty=difficulty,
        game_id=game_id,
    )


def _migrate_profile(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("profile must be an object")
    profile = copy.deepcopy(DEFAULT_PROFILE)
    if isinstance(data.get("player_name"), str):
        profile["player_name"] = data["player_name"]
    if isinstance(data.get("preferences"), dict):
        profile["preferences"].update(data["preferences"])
    if isinstance(data.get("statistics"), dict):
        source_stats = data["statistics"]
        profile["statistics"].update(
            {
                key: value
                for key, value in source_stats.items()
                if key in profile["statistics"] and key != "by_difficulty"
            }
        )
        source_by_difficulty = source_stats.get("by_difficulty", {})
        if "total_matches" in source_stats and isinstance(source_by_difficulty, dict):
            profile["statistics"]["by_difficulty"] = source_by_difficulty
        if "total_rounds" not in source_stats and "total_games" in source_stats:
            profile["statistics"]["total_rounds"] = int(source_stats.get("total_games", 0))
            profile["statistics"]["head_rounds"] = int(source_stats.get("wins", 0))
            total_rounds = profile["statistics"]["total_rounds"]
            profile["statistics"]["head_rate"] = (
                profile["statistics"]["head_rounds"] / total_rounds if total_rounds else 0.0
            )
            if isinstance(source_by_difficulty, dict):
                profile["statistics"]["by_difficulty_rounds"] = {
                    str(key): {
                        "rounds": int(value.get("games", 0)),
                        "heads": int(value.get("wins", 0)),
                    }
                    for key, value in source_by_difficulty.items()
                    if isinstance(value, dict)
                }
    recorded = profile["statistics"].get("recorded_game_ids", [])
    profile["statistics"]["recorded_game_ids"] = (
        [item for item in recorded if isinstance(item, str)]
        if isinstance(recorded, list)
        else []
    )
    recorded_matches = profile["statistics"].get("recorded_match_ids", [])
    profile["statistics"]["recorded_match_ids"] = (
        [item for item in recorded_matches if isinstance(item, str)]
        if isinstance(recorded_matches, list)
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
    "record_match_statistics",
    "record_round_statistics",
    "save_profile",
    "update_profile",
    "update_statistics",
]

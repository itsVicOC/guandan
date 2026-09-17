"""用户配置和统计管理。

Profile 包含：
- 用户偏好（默认难度、提示开关）
- 小局头游统计与成功过 A 后的整场比赛胜负统计
"""
from __future__ import annotations

import copy
import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, TypeVar

from .jsonio import write_json_atomic
from .locking import storage_lock
from .paths import get_profile_path

PROFILE_VERSION = "3.0"
_ResultT = TypeVar("_ResultT")

_profile_error_guard = Lock()
_last_profile_error: str | None = None

# Integer counters the settlement path increments with int(...) arithmetic.
_COUNTED_STAT_KEYS = (
    "total_rounds",
    "head_rounds",
    "total_matches",
    "match_wins",
    "match_losses",
    "total_games",
    "wins",
)

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
        # Settlements that started but did not finish; repaired on next start.
        # Must be part of the schema: _migrate_profile drops unknown keys, so an
        # unlisted field would never survive a single load.
        "pending_settlements": [],
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


def _quarantine_corrupt_profile(path: Path, reason: str) -> Path | None:
    """Move an unreadable profile aside so the next write cannot destroy it.

    The old behaviour returned defaults and let the following write overwrite
    the user's statistics in place — a silent, unrecoverable data loss. Keeping
    the bytes on disk lets a user (or support) recover the history by hand.
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for attempt in range(100):
        suffix = "" if attempt == 0 else f"-{attempt}"
        target = path.with_name(f"{path.name}.corrupt-{timestamp}{suffix}")
        if target.exists():
            continue
        try:
            os.replace(path, target)
        except OSError:
            return None
        _report_profile_error(f"{reason}；原文件已备份为 {target.name}")
        return target
    return None


def _report_profile_error(message: str) -> None:
    """Record the last load problem so a frontend can surface it once."""
    global _last_profile_error
    with _profile_error_guard:
        _last_profile_error = message


def consume_profile_error() -> str | None:
    """Return and clear the last profile load error, if any."""
    global _last_profile_error
    with _profile_error_guard:
        message = _last_profile_error
        _last_profile_error = None
    return message


def _load_profile_unlocked(path: Path) -> dict[str, Any]:
    if not path.exists():
        return copy.deepcopy(DEFAULT_PROFILE)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return copy.deepcopy(DEFAULT_PROFILE)
    except OSError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Unparseable file: preserve it instead of overwriting it later.
        _quarantine_corrupt_profile(path, "配置文件无法解析")
        return copy.deepcopy(DEFAULT_PROFILE)

    try:
        profile = _migrate_profile(data)
    except (KeyError, TypeError, ValueError) as exc:
        # Parseable but structurally wrong (e.g. hand-edited statistics). The
        # values are recoverable per field, so keep the file and fall back to
        # defaults without quarantining.
        _report_profile_error(f"配置内容异常（{exc}），已使用默认统计")
        return copy.deepcopy(DEFAULT_PROFILE)
    _validate_profile_statistics(profile)
    return profile


def _validate_profile_statistics(profile: dict[str, Any]) -> None:
    """Guarantee the statistics shape callers index into without checks.

    ``record_round_statistics`` and friends do ``profile["statistics"][...]``
    and ``int(stats.get(...))`` directly, so a malformed nested value must
    never escape this module — otherwise a hand-edited profile would abort the
    whole settlement transaction instead of just losing one counter.
    """
    statistics = profile.get("statistics")
    if not isinstance(statistics, dict):
        raise ValueError("statistics must be an object")
    for key in ("by_difficulty", "by_difficulty_rounds"):
        bucket = statistics.get(key)
        if not isinstance(bucket, dict):
            statistics[key] = {}
            continue
        for bucket_key, value in list(bucket.items()):
            if not isinstance(value, dict):
                bucket[bucket_key] = {"matches": 0, "wins": 0, "rounds": 0}
    for key in ("recorded_game_ids", "recorded_match_ids"):
        if not isinstance(statistics.get(key), list):
            statistics[key] = []
    for key in _COUNTED_STAT_KEYS:
        value = statistics.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = 0
        statistics[key] = max(0, int(value))


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


# ---- 结算补偿（settlement reconciliation） ----
#
# Settling a round is three separate durable writes — history file, profile
# statistics, then delete the savegame. A crash between them left the history
# entry without its statistics forever, because the idempotency key is only
# written after the statistics update succeeds.
#
# The fix is to log the *intent* first: `begin_settlement()` persists a marker,
# the caller does the writes, then `end_settlement()` removes it. Whatever is
# still marked on the next start is a settlement that did not finish.


def begin_settlement(
    *,
    game_id: str,
    got_head: bool,
    difficulty: int,
    match_id: str | None = None,
    match_won: bool | None = None,
) -> None:
    """Record that a round settlement is about to happen."""

    def mutator(profile: dict[str, Any]) -> None:
        statistics = profile["statistics"]
        pending = statistics.setdefault("pending_settlements", [])
        pending[:] = [item for item in pending if item.get("game_id") != game_id]
        entry: dict[str, Any] = {
            "game_id": game_id,
            "got_head": bool(got_head),
            "difficulty": int(difficulty),
        }
        if match_id is not None:
            entry["match_id"] = match_id
            entry["match_won"] = bool(match_won)
        pending.append(entry)

    update_profile(mutator)


def end_settlement(game_id: str) -> None:
    """Clear the marker once every write of the settlement has completed."""

    def mutator(profile: dict[str, Any]) -> None:
        statistics = profile["statistics"]
        pending = statistics.setdefault("pending_settlements", [])
        pending[:] = [item for item in pending if item.get("game_id") != game_id]

    update_profile(mutator)


def reconcile_settlements(*, history_has_game: Callable[[str], bool]) -> int:
    """Finish settlements interrupted by a crash; returns how many were closed.

    Recording is idempotent (keyed on ``game_id``), so re-running one is safe;
    the only question is whether the round was already counted.
    """
    repaired = 0

    def mutator(profile: dict[str, Any]) -> int:
        statistics = profile["statistics"]
        pending = statistics.setdefault("pending_settlements", [])
        remaining: list[dict[str, Any]] = []
        count = 0
        for item in pending:
            game_id = str(item.get("game_id", ""))
            if not game_id:
                remaining.append(item)
                continue
            # A missing history entry means the crash happened before the
            # history write; the round was never shown to the user, so it is
            # dropped rather than invented.
            if not history_has_game(game_id):
                continue
            record_round_statistics(
                profile,
                got_head=bool(item.get("got_head")),
                difficulty=int(item.get("difficulty", 0)),
                game_id=game_id,
            )
            match_id = item.get("match_id")
            if isinstance(match_id, str) and match_id:
                record_match_statistics(
                    profile,
                    won=bool(item.get("match_won")),
                    difficulty=int(item.get("difficulty", 0)),
                    match_id=match_id,
                )
            count += 1
        statistics["pending_settlements"] = remaining
        return count

    repaired = update_profile(mutator)
    return int(repaired)


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
    pending = profile["statistics"].get("pending_settlements", [])
    profile["statistics"]["pending_settlements"] = (
        [item for item in pending if isinstance(item, dict)]
        if isinstance(pending, list)
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

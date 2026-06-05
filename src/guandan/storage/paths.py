"""路径管理：获取存储目录和文件路径。

存储结构：
~/.guandan/
├── profile.json      # 用户配置和统计
├── savegame.json     # 当前未完成的对局（单个）
└── history/          # 历史对局记录（多个）
    ├── 2026-06-05_143521_game001.json
    └── ...
"""
from __future__ import annotations

from pathlib import Path


def get_storage_dir() -> Path:
    """获取存储目录 ~/.guandan/

    目录不存在时自动创建。

    Returns:
        存储目录路径
    """
    storage_dir = Path.home() / ".guandan"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def get_profile_path() -> Path:
    """获取用户配置文件路径 ~/.guandan/profile.json

    Returns:
        配置文件路径
    """
    return get_storage_dir() / "profile.json"


def get_savegame_path() -> Path:
    """获取存档文件路径 ~/.guandan/savegame.json

    Returns:
        存档文件路径
    """
    return get_storage_dir() / "savegame.json"


def get_history_dir() -> Path:
    """获取历史记录目录 ~/.guandan/history/

    目录不存在时自动创建。

    Returns:
        历史记录目录路径
    """
    history_dir = get_storage_dir() / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir


__all__ = [
    "get_storage_dir",
    "get_profile_path",
    "get_savegame_path",
    "get_history_dir",
]

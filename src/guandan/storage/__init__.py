"""持久化包：profile / replay / savegame。

M5 实现完整的存储系统：
- Profile：用户配置和统计
- Savegame：断点续局
- History：对局回放

存储位置：~/.guandan/
"""
from __future__ import annotations

from .history import load_history_detail, load_history_list, save_history
from .paths import (
    get_history_dir,
    get_profile_path,
    get_savegame_path,
    get_storage_dir,
)
from .profile import (
    DEFAULT_PROFILE,
    load_profile,
    save_profile,
    update_statistics,
)
from .savegame import delete_savegame, has_savegame, load_game, restore_game_state, save_game
from .serialization import deserialize_events, serialize_events

__all__ = [
    "DEFAULT_PROFILE",
    "delete_savegame",
    "deserialize_events",
    "get_history_dir",
    "get_profile_path",
    "get_savegame_path",
    "get_storage_dir",
    "has_savegame",
    "load_game",
    "load_history_detail",
    "load_history_list",
    "load_profile",
    "restore_game_state",
    "save_game",
    "save_history",
    "save_profile",
    "serialize_events",
    "update_statistics",
]

"""Preview or rebuild statistics from validated history: python -m guandan.storage.maintenance."""
from __future__ import annotations

import argparse
import copy
import json
import uuid
from typing import Any

from ..engine.replay import replay_events
from ..engine.state import IllegalPlayError
from .jsonio import write_json_atomic
from .locking import storage_lock
from .paths import get_history_dir, get_profile_path, validate_game_id
from .profile import (
    DEFAULT_PROFILE,
    record_match_statistics,
    record_round_statistics,
    update_profile,
)
from .serialization import deserialize_events


def rebuild_statistics(*, apply: bool = False) -> dict[str, Any]:
    """Never replace statistics if a history record cannot be validated."""
    rebuilt = copy.deepcopy(DEFAULT_PROFILE)
    invalid = []
    directory = get_history_dir()
    # Same lock order as settlement: do not retain the profile lock while
    # waiting for history. update_profile serializes concurrent statistics.
    with storage_lock(directory):
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                state = replay_events(deserialize_events(data["events"]),
                                      ruleset_version=data.get("ruleset_version", 1))
                human = data["metadata"]["player_seat"]
                if not state.finished or type(human) is not int or human not in range(4):
                    raise ValueError("history is not a completed round")
                difficulty = next(d for d in data["metadata"]["ai_difficulties"] if d is not None)
                if type(difficulty) is not int or difficulty not in range(5):
                    raise ValueError("invalid difficulty")
                record_round_statistics(rebuilt, got_head=state.finish_order[0] == human,
                                        difficulty=difficulty, game_id=validate_game_id(data["game_id"]))
                if state.match_finished:
                    record_match_statistics(rebuilt, won=state.winner_team == human % 2,
                                            difficulty=difficulty,
                                            match_id=validate_game_id(data.get("match_id", data["game_id"])))
            except (OSError, ValueError, TypeError, KeyError, IndexError, StopIteration, IllegalPlayError):
                invalid.append(path.name)
        backup_path = None
        if apply:
            if invalid:
                raise ValueError("历史记录有损坏，未更改统计：" + ", ".join(invalid))

            def replace(profile: dict[str, Any]) -> None:
                nonlocal backup_path
                # Refuse to race a settlement whose history is not yet durable.
                if profile["statistics"].get("pending_settlements"):
                    raise OSError("存在待完成结算，请重启游戏完成结算后再重建")
                backup_path = get_profile_path().with_name(f"profile.json.rebuild-{uuid.uuid4().hex}")
                write_json_atomic(backup_path, profile)
                profile["statistics"] = rebuilt["statistics"]

            update_profile(replace)
    return {"statistics": rebuilt["statistics"], "invalid_files": invalid,
            "applied": apply, "backup": str(backup_path) if backup_path else None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="apply the preview and retain a profile backup")
    args = parser.parse_args()
    print(json.dumps(rebuild_statistics(apply=args.apply), ensure_ascii=False, indent=2))

"""游戏存档管理：断点续局。

存档包含：
- 完整事件流（可重建状态）
- 当前状态快照（快速显示）
- 完整状态快照（直接恢复续局）
- 元数据（玩家座位、AI 难度、种子）
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from ..engine.card import Card, Suit
from ..engine.events import Pass, ShuffleDeal, TurnPlayed
from ..engine.hand import Pattern, PatternType
from ..engine.state import GameState, TributeState, make_initial_state, pass_turn, play_pattern
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
        "state": _state_to_dict(state),
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
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        # 反序列化事件流
        data["events"] = deserialize_events(data["events"])

        return data
    except (OSError, json.JSONDecodeError, ValueError):
        # 文件损坏
        return None


def restore_game_state(savegame: dict[str, Any]) -> GameState:
    """从存档数据恢复可继续游玩的 GameState。

    新版存档包含完整 `state` 快照，优先直接恢复。旧版存档没有完整
    手牌快照时，退回到 `seed + events` 重放。
    """
    if savegame.get("state"):
        return _dict_to_state(savegame["state"], savegame.get("events", []))
    return _replay_events_to_state(savegame)


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
    "delete_savegame",
    "has_savegame",
    "load_game",
    "restore_game_state",
    "save_game",
]


def _card_to_dict(card: Card) -> dict[str, Any]:
    return {"rank": card.rank, "suit": int(card.suit)}


def _dict_to_card(data: dict[str, Any]) -> Card:
    return Card(rank=data["rank"], suit=Suit(data["suit"]))


def _pattern_to_dict(pattern: Pattern) -> dict[str, Any]:
    return {
        "type": pattern.type.value,
        "rank": pattern.rank,
        "length": pattern.length,
        "cards": [_card_to_dict(c) for c in pattern.cards],
        "wild_used": pattern.wild_used,
        "suit": pattern.suit,
    }


def _dict_to_pattern(data: dict[str, Any]) -> Pattern:
    return Pattern(
        type=PatternType(data["type"]),
        rank=data["rank"],
        length=data["length"],
        cards=tuple(_dict_to_card(c) for c in data["cards"]),
        wild_used=data.get("wild_used", 0),
        suit=data.get("suit"),
    )


def _tribute_state_to_dict(tribute: TributeState) -> dict[str, Any]:
    return {
        "pending": tribute.pending,
        "from_player": tribute.from_player,
        "to_player": tribute.to_player,
        "tribute_card": _card_to_dict(tribute.tribute_card) if tribute.tribute_card else None,
        "resisted": tribute.resisted,
    }


def _dict_to_tribute_state(data: dict[str, Any]) -> TributeState:
    return TributeState(
        pending=data.get("pending", False),
        from_player=data.get("from_player", -1),
        to_player=data.get("to_player", -1),
        tribute_card=_dict_to_card(data["tribute_card"]) if data.get("tribute_card") else None,
        resisted=data.get("resisted", False),
    )


def _state_to_dict(state: GameState) -> dict[str, Any]:
    return {
        "level": state.level,
        "wild_card": _card_to_dict(state.wild_card) if state.wild_card else None,
        "hands": [[_card_to_dict(c) for c in hand] for hand in state.hands],
        "turn_index": state.turn_index,
        "team_levels": list(state.team_levels),
        "table": [_pattern_to_dict(p) for p in state.table],
        "passed_players": sorted(state.passed_players),
        "leader": state.leader,
        "finish_order": list(state.finish_order),
        "team_bomb_count": list(state.team_bomb_count),
        "has_played_ace": list(state.has_played_ace),
        "finished": state.finished,
        "tribute_state": _tribute_state_to_dict(state.tribute_state),
        "drift": state.drift,
        "trick_number": state.trick_number,
        "next_trick_starter": state.next_trick_starter,
        "team_levels_final": list(state.team_levels_final)
        if state.team_levels_final
        else None,
        "drift_flag": state.drift_flag,
        "guo_a": state.guo_a,
        "guo_a_failed": state.guo_a_failed,
    }


def _dict_to_state(data: dict[str, Any], events: list[Any]) -> GameState:
    state = GameState(
        level=data["level"],
        wild_card=_dict_to_card(data["wild_card"]) if data.get("wild_card") else None,
        hands=[[_dict_to_card(c) for c in hand] for hand in data["hands"]],
        turn_index=data["turn_index"],
        team_levels=list(data.get("team_levels", [data["level"], data["level"]])),
        table=[_dict_to_pattern(p) for p in data.get("table", [])],
        passed_players=set(data.get("passed_players", [])),
        leader=data.get("leader"),
        history=list(events),
        finish_order=list(data.get("finish_order", [])),
        team_bomb_count=list(data.get("team_bomb_count", [0, 0])),
        has_played_ace=list(data.get("has_played_ace", [False, False])),
        finished=data.get("finished", False),
        tribute_state=_dict_to_tribute_state(data.get("tribute_state", {})),
        drift=data.get("drift", False),
        trick_number=data.get("trick_number", 0),
        next_trick_starter=data.get("next_trick_starter"),
        team_levels_final=list(data["team_levels_final"])
        if data.get("team_levels_final")
        else None,
        drift_flag=data.get("drift_flag", False),
        guo_a=data.get("guo_a", False),
        guo_a_failed=data.get("guo_a_failed", False),
    )
    return state


def _replay_events_to_state(savegame: dict[str, Any]) -> GameState:
    events = savegame.get("events") or []
    shuffle = next((ev for ev in events if isinstance(ev, ShuffleDeal)), None)
    if shuffle is None:
        raise ValueError("Savegame has no ShuffleDeal event")

    state = make_initial_state(
        level=shuffle.level,
        first_player=shuffle.first_player,
        seed=shuffle.seed,
        team_levels=shuffle.team_levels,
    )
    for event in events[1:]:
        if state.finished:
            break
        if isinstance(event, TurnPlayed):
            play_pattern(state, event.player, event.pattern)
        elif isinstance(event, Pass):
            pass_turn(state, event.player)
    return state

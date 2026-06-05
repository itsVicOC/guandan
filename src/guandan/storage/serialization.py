"""事件序列化/反序列化：Event ↔ dict ↔ JSON。

支持所有事件类型的往返转换。
"""
from __future__ import annotations

from typing import Any

from ..engine.card import Card, Suit
from ..engine.events import Event, event_to_dict
from ..engine.hand import Pattern, PatternType


def serialize_events(events: list[Event]) -> list[dict[str, Any]]:
    """事件流 → JSON 可序列化的 list[dict]

    Args:
        events: 事件列表

    Returns:
        字典列表（可直接 json.dump）
    """
    return [event_to_dict(ev) for ev in events]


def deserialize_events(dicts: list[dict[str, Any]]) -> list[Event]:
    """list[dict] → 事件流

    Args:
        dicts: 字典列表（从 json.load 得到）

    Returns:
        事件列表

    Raises:
        ValueError: 事件类型未知或格式错误
    """
    return [dict_to_event(d.copy()) for d in dicts]


def dict_to_event(d: dict[str, Any]) -> Event:
    """dict → Event（反序列化单个事件）

    Args:
        d: 事件字典（包含 _type 字段）

    Returns:
        事件对象

    Raises:
        ValueError: 事件类型未知或格式错误
    """
    from ..engine import events

    event_type = d.pop("_type")

    try:
        event_class = getattr(events, event_type)
    except AttributeError:
        raise ValueError(f"Unknown event type: {event_type}")

    # 递归转换嵌套对象
    if event_type == "TurnPlayed":
        d["pattern"] = _dict_to_pattern(d["pattern"])
    elif event_type in ("TributeSent", "TributeReturned"):
        d["card"] = _dict_to_card(d["card"])
    elif event_type == "ShuffleDeal" and d.get("wild_card"):
        d["wild_card"] = _dict_to_card(d["wild_card"])

    # 转换 tuple（JSON 会把 tuple 变成 list）
    if event_type == "ShuffleDeal":
        d["hand_sizes"] = tuple(d["hand_sizes"])
    elif event_type == "GameOver":
        d["finish_order"] = tuple(d["finish_order"])
        d["team_levels"] = tuple(d["team_levels"])

    return event_class(**d)


def _dict_to_card(d: dict[str, Any]) -> Card:
    """dict → Card

    Args:
        d: 卡牌字典 {"rank": int, "suit": Suit or str}

    Returns:
        Card 对象
    """
    suit_value = d["suit"]
    # 处理 dataclasses.asdict 不转换 Enum 的情况
    if isinstance(suit_value, Suit):
        # 直接是 Enum 对象
        suit = suit_value
    elif isinstance(suit_value, str):
        # 字符串形式
        suit = Suit[suit_value]
    elif isinstance(suit_value, int):
        # 整数值
        suit = Suit(suit_value)
    else:
        raise ValueError(f"Unknown suit format: {suit_value}")

    return Card(rank=d["rank"], suit=suit)


def _dict_to_pattern(d: dict[str, Any]) -> Pattern:
    """dict → Pattern

    Args:
        d: 牌型字典 {"cards": [...], "type": str, "rank": int, "length": int}

    Returns:
        Pattern 对象
    """
    cards = [_dict_to_card(c) for c in d["cards"]]

    # 处理 PatternType 序列化
    pattern_type = d["type"]
    if isinstance(pattern_type, PatternType):
        # 直接是 Enum 对象（dataclasses.asdict 不会转换 Enum）
        pattern_type_enum = pattern_type
    elif isinstance(pattern_type, str):
        # 字符串形式
        pattern_type_enum = PatternType[pattern_type]
    else:
        raise ValueError(f"Unknown pattern type format: {pattern_type}")

    return Pattern(
        cards=tuple(cards),
        type=pattern_type_enum,
        rank=d["rank"],
        length=d["length"],
    )


__all__ = [
    "serialize_events",
    "deserialize_events",
    "dict_to_event",
]

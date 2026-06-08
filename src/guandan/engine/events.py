"""事件流：对局过程中所有事件的不可变记录。

设计：每个事件是一个 frozen dataclass，描述游戏中的一次原子操作。
所有事件组成一个 list，构成完整的"对局回放"。

事件类型：
- ShuffleDeal: 一局开始发牌
- TurnPlayed: 玩家出牌
- Pass: 玩家过牌
- Claim: 玩家报牌（剩余张数）
- TributeSent: 进贡
- TributeReturned: 还贡
- TributeResisted: 抗贡
- Drift: 漂牌
- LevelUp: 升级
- GameOver: 一局结束
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Union

from .card import Card
from .hand import Pattern

# ---- 事件类型 ----


@dataclass(frozen=True)
class ShuffleDeal:
    level: int  # 本局级牌点数（2-14）
    wild_card: Optional[Card]  # 逢人配（红心级牌），若级牌不是红桃则为 None
    hand_sizes: tuple[int, int, int, int]  # 每人手牌数
    first_player: int  # 首发起家索引 (0-3)
    # 出于反作弊：保存种子，让他人能复现
    seed: int


@dataclass(frozen=True)
class TurnPlayed:
    player: int
    pattern: Pattern
    hand_remaining: int


@dataclass(frozen=True)
class Pass:
    player: int
    hand_remaining: int


@dataclass(frozen=True)
class Claim:
    """报牌：玩家手牌 ≤ 10 时报张数。"""

    player: int
    count: int  # 报出的张数


@dataclass(frozen=True)
class TributeSent:
    """进贡：from 给 to 一张牌。"""

    from_player: int
    to_player: int
    card: Card


@dataclass(frozen=True)
class TributeReturned:
    """还贡：from 给 to 一张牌。"""

    from_player: int
    to_player: int
    card: Card


@dataclass(frozen=True)
class TributeResisted:
    """抗贡：player 拒绝进贡。"""

    player: int


@dataclass(frozen=True)
class Drift:
    """漂牌：上游最后一手为 5 张+级牌炸弹，额外升 3 级。"""

    player: int
    bonus_levels: int = 3


@dataclass(frozen=True)
class LevelUp:
    """升级。"""

    team: int  # 0=东-西队，1=南-北队
    new_level: int  # 升级后的级牌
    delta: int  # 升级多少


@dataclass(frozen=True)
class GameOver:
    """一局结束。"""

    finish_order: tuple[int, int, int, int]  # 上游到下游的玩家顺序
    team_levels: tuple[int, int]  # 两队当前级牌
    drift: bool
    guo_a: bool  # 是否过 A


# 所有事件类型
Event = Union[
    ShuffleDeal,
    TurnPlayed,
    Pass,
    Claim,
    TributeSent,
    TributeReturned,
    TributeResisted,
    Drift,
    LevelUp,
    GameOver,
]


def event_to_dict(ev: Event) -> dict[str, Any]:
    """把事件转成可 JSON 序列化的 dict。"""
    import dataclasses

    d = dataclasses.asdict(ev)
    d["_type"] = type(ev).__name__
    return d

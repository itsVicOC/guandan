"""牌型大小比较。

主要逻辑已经在 Pattern.can_be_played_on 中实现。本模块提供更细粒度的工具函数。
"""
from __future__ import annotations

from typing import Optional

from ..hand import Pattern, PatternType, comparison_rank


def can_play(
    play: Pattern, against: Optional[Pattern], *, level: int | None = None
) -> bool:
    """判断 play 能否压 against。

    against=None 表示 play 是新一轮先手，任何合法牌型都允许。
    """
    if against is None:
        return True
    return play.can_be_played_on(against, level=level)


def compare_same_type(
    p1: Pattern, p2: Pattern, *, level: int | None = None
) -> int:
    """同类型牌型比大小。返回 1 (p1 大), -1 (p2 大), 0 (相等)。

    不要求 p1 和 p2 同类型——同类型才有意义。
    """
    if p1.type != p2.type:
        raise ValueError(f"patterns must be same type: {p1.type} vs {p2.type}")
    if p1.length != p2.length:
        raise ValueError(f"patterns must be same length: {p1.length} vs {p2.length}")
    r1 = comparison_rank(p1, level)
    r2 = comparison_rank(p2, level)
    if r1 > r2:
        return 1
    if r1 < r2:
        return -1
    return 0


def is_bomb_type(t: PatternType) -> bool:
    """是否是炸弹类（含四王）。"""
    return t in (PatternType.BOMB, PatternType.STRAIGHT_FLUSH, PatternType.FOUR_JOKERS)


def bomb_strength(p: Pattern, *, level: int | None = None) -> tuple[int, int, int]:
    """炸弹的"强度"三元组，用于跨类型比较。

    返回 (category, length, rank)：
    - category: 0=BOMB, 1=STRAIGHT_FLUSH, 2=FOUR_JOKERS（越大越强）
    - length: 炸弹张数（越大越强）
    - rank: 炸弹点数（越大越强）

    同 category 比 length，再比 rank。
    """
    rank = comparison_rank(p, level)
    if p.type == PatternType.BOMB:
        return (0, p.length, rank)
    if p.type == PatternType.STRAIGHT_FLUSH:
        return (1, p.length, rank)
    if p.type == PatternType.FOUR_JOKERS:
        return (2, p.length, rank)
    raise ValueError(f"not a bomb: {p.type}")


def compare_bombs(p1: Pattern, p2: Pattern, *, level: int | None = None) -> int:
    """两个炸弹比大小。返回 1 (p1 大), -1 (p2 大), 0 (相等)。"""
    if not is_bomb_type(p1.type) or not is_bomb_type(p2.type):
        raise ValueError(f"not bombs: {p1.type} vs {p2.type}")
    if p1.can_be_played_on(p2, level=level):
        return 1
    if p2.can_be_played_on(p1, level=level):
        return -1
    return 0

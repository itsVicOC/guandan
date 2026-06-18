"""手牌（Hand）与牌型（Pattern）。

Hand: 玩家手中牌的集合 + 已知信息
PatternType: 牌型枚举
Pattern: 已识别的牌型，含 rank / cards / wild_used
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum

from .card import RANK_A, RANK_BIG_JOKER, RANK_SMALL_JOKER, Card


class PatternType(str, Enum):
    """牌型枚举。

    用 str 继承以便 JSON 序列化。排序权重见 WEIGHT，用于比较"哪个牌型更大"。
    """

    SINGLE = "single"
    PAIR = "pair"
    TRIPLE = "triple"
    TRIPLE_PAIR = "triple_pair"  # 三带二（三张 + 一对子）
    STRAIGHT = "straight"  # 固定 5 张连续单张
    PAIR_SEQUENCE = "pair_sequence"  # 3+ 对连续对子
    TRIPLE_SEQUENCE = "triple_sequence"  # 2+ 组连续三张（钢板）
    BOMB = "bomb"  # 4+ 张同点
    STRAIGHT_FLUSH = "straight_flush"  # 固定 5 张同花色顺子
    FOUR_JOKERS = "four_jokers"  # 四王炸弹


# 牌型比较权重（同类型之间用 rank 比，跨类型用 weight 比"牌型类别大小"）。
# 数字越大牌型类别越大：炸弹 > 顺子 > 三带二 > ...；四王最大
PATTERN_WEIGHT: dict[PatternType, int] = {
    PatternType.SINGLE: 0,
    PatternType.PAIR: 1,
    PatternType.TRIPLE: 2,
    PatternType.TRIPLE_PAIR: 3,
    PatternType.PAIR_SEQUENCE: 4,
    PatternType.TRIPLE_SEQUENCE: 5,
    PatternType.STRAIGHT: 6,
    PatternType.BOMB: 10,
    PatternType.STRAIGHT_FLUSH: 11,
    PatternType.FOUR_JOKERS: 20,
}


SEQUENCE_PATTERN_TYPES = {
    PatternType.STRAIGHT,
    PatternType.PAIR_SEQUENCE,
    PatternType.TRIPLE_SEQUENCE,
    PatternType.STRAIGHT_FLUSH,
}


def effective_rank(rank: int, level: int | None = None) -> int:
    """用于比较的有效点数：级牌是最大的非王牌。"""
    if rank in (RANK_SMALL_JOKER, RANK_BIG_JOKER):
        return rank
    if level is not None and rank == level:
        return RANK_A + 1
    return rank


def comparison_rank(pattern: Pattern, level: int | None = None) -> int:
    """用于牌型比较的点数；顺子类不套用级牌特殊强度。"""
    if pattern.type in SEQUENCE_PATTERN_TYPES:
        return pattern.rank
    return effective_rank(pattern.rank, level)


@dataclass(frozen=True)
class Pattern:
    """已识别的合法牌型。

    - type: 牌型类别
    - rank: 比较点数（顺子用最大张的点数，炸弹用点数，三带二用三张的点数，等等）
    - length: 牌型长度（顺子张数 / 炸弹张数 / 连对对数 ...）；同类型相同时 length 也可比
    - cards: 实际使用的牌（含 wild）
    - wild_used: 本牌型用了几张逢人配
    - suit: 花色（仅同花顺用得到）
    """

    type: PatternType
    rank: int
    length: int
    cards: tuple[Card, ...]
    wild_used: int = 0
    suit: int | None = None  # 仅同花顺用

    @property
    def weight(self) -> int:
        return PATTERN_WEIGHT[self.type]

    def can_be_played_on(self, other: Pattern, *, level: int | None = None) -> bool:
        """判断本牌型是否能压 other。

        规则：
        - 炸弹 / 同花顺 / 四王 可压任何非炸弹
        - 四王 压所有
        - 同类型之间比 rank（必要时比 length）
        """
        if other.type == PatternType.FOUR_JOKERS:
            return False
        # 四王最大
        if self.type == PatternType.FOUR_JOKERS:
            return True
        # 炸弹类
        if self.type in (PatternType.BOMB, PatternType.STRAIGHT_FLUSH):
            if other.type in (PatternType.BOMB, PatternType.STRAIGHT_FLUSH):
                if self.type != other.type:
                    # 5 张同花顺可压 4 张或 5 张普通炸弹；6+ 普通炸弹可反压同花顺。
                    if self.type == PatternType.STRAIGHT_FLUSH:
                        return (
                            other.type == PatternType.BOMB
                            and self.length == 5
                            and other.length in (4, 5)
                        )
                    if self.type == PatternType.BOMB:
                        return other.type == PatternType.STRAIGHT_FLUSH and self.length >= 6
                    return False
                # 同 type: 先 length 再 rank
                if self.length != other.length:
                    return self.length > other.length
                return comparison_rank(self, level) > comparison_rank(other, level)
            # 炸弹压任何非炸弹
            return True
        if other.type in (PatternType.BOMB, PatternType.STRAIGHT_FLUSH):
            return False
        # 同非炸弹类型之间
        if self.type != other.type:
            return False
        if self.length != other.length:
            # 同类型但长度不同（如顺子 5 张 vs 6 张）——掼蛋里同类型必须同长度
            return False
        return comparison_rank(self, level) > comparison_rank(other, level)

    def __repr__(self) -> str:
        cards_str = " ".join(c.short for c in self.cards)
        return f"Pattern({self.type.value}, rank={self.rank}, len={self.length}, cards=[{cards_str}])"


@dataclass
class Hand:
    """玩家手牌（可变容器，便于 add/remove）。

    注意：Hand 是 mutable，但 Card 是 immutable。这避免在 add/remove 时
    重新生成大量 Card 对象。
    """

    cards: list[Card] = field(default_factory=list)

    def __post_init__(self) -> None:
        # 保持稳定顺序（按 rank 升序 / 同 rank 按 suit 升序）
        self.cards.sort()

    def __len__(self) -> int:
        return len(self.cards)

    def __iter__(self):
        return iter(self.cards)

    def __contains__(self, card: Card) -> bool:
        return card in self.cards

    def add(self, card: Card) -> None:
        self.cards.append(card)
        self.cards.sort()

    def add_many(self, cards: Iterable[Card]) -> None:
        for c in cards:
            self.cards.append(c)
        self.cards.sort()

    def remove(self, card: Card) -> None:
        self.cards.remove(card)

    def remove_many(self, cards: Iterable[Card]) -> None:
        for c in cards:
            self.cards.remove(c)

    def take(self, n: int) -> list[Card]:
        """取前 n 张（按排序顺序），并从手牌中删除。"""
        taken = self.cards[:n]
        del self.cards[:n]
        return taken

    def copy(self) -> Hand:
        return Hand(list(self.cards))

    def to_tuple(self) -> tuple[Card, ...]:
        return tuple(self.cards)

    def is_empty(self) -> bool:
        return len(self.cards) == 0

    def count_by_rank(self) -> dict[int, int]:
        """按 rank 统计每种点数的张数。"""
        result: dict[int, int] = {}
        for c in self.cards:
            result[c.rank] = result.get(c.rank, 0) + 1
        return result

    def ranks(self) -> list[int]:
        """所有牌的 rank 列表。"""
        return [c.rank for c in self.cards]


def sort_hand(h: Hand) -> Hand:
    """返回按从大到小排序的 Hand（王在前，2 在后）。

    实现：构造一个空 Hand，逐张 add（add 会保持升序），然后再 reverse 列表。
    或者直接绕过 __post_init__ 排序。最简单：直接 new Hand，构造后再 reverse。
    """
    new_hand = Hand(list(h.cards))
    new_hand.cards.reverse()
    return new_hand


def sort_cards(cards: Sequence[Card]) -> list[Card]:
    """按从大到小排序：王 > A > K > ... > 2。"""
    return sorted(cards, reverse=True)

"""牌（Card）数据类。

- rank: 2..14 标准点数；100=小王；101=大王
- suit: 花色（红桃/方块/梅花/黑桃）或王（小红/小王）
- 是否为"逢人配"（万能牌）由 game level + suit=红桃 决定，不存在 Card 属性上

设计原则：
- 不可变（frozen=True），可哈希、可放入 set
- 顺序：大王 > 小王 > A > K > Q > J > 10 > ... > 2（按 rank 升序排列时实际是降序）
- 花色顺序仅用于显示，不参与牌力比较
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Suit(IntEnum):
    """花色。IntEnum 便于序列化与比较。

    顺序（按中国掼蛋习惯）：红桃 > 方块 > 黑桃 > 梅花；王排在最前。
    """

    SMALL_JOKER = 0  # 小王
    BIG_JOKER = 1  # 大王
    HEARTS = 2  # 红桃
    DIAMONDS = 3  # 方块
    SPADES = 4  # 黑桃
    CLUBS = 5  # 梅花

    @property
    def is_joker(self) -> bool:
        return self in (Suit.SMALL_JOKER, Suit.BIG_JOKER)

    @property
    def cn(self) -> str:
        return _SUIT_CN.get(self, "?")


_SUIT_CN = {
    Suit.SMALL_JOKER: "小王",
    Suit.BIG_JOKER: "大王",
    Suit.HEARTS: "红桃",
    Suit.DIAMONDS: "方块",
    Suit.SPADES: "黑桃",
    Suit.CLUBS: "梅花",
}


# 标准点数常量
RANK_2 = 2
RANK_3 = 3
RANK_4 = 4
RANK_5 = 5
RANK_6 = 6
RANK_7 = 7
RANK_8 = 8
RANK_9 = 9
RANK_10 = 10
RANK_J = 11
RANK_Q = 12
RANK_K = 13
RANK_A = 14
RANK_SMALL_JOKER = 100
RANK_BIG_JOKER = 101

# 普通牌点数范围
NORMAL_MIN = RANK_2
NORMAL_MAX = RANK_A

# 牌面中文
_RANK_CN = {
    RANK_2: "2",
    RANK_3: "3",
    RANK_4: "4",
    RANK_5: "5",
    RANK_6: "6",
    RANK_7: "7",
    RANK_8: "8",
    RANK_9: "9",
    RANK_10: "10",
    RANK_J: "J",
    RANK_Q: "Q",
    RANK_K: "K",
    RANK_A: "A",
    RANK_SMALL_JOKER: "joker",
    RANK_BIG_JOKER: "JOKER",
}


@dataclass(frozen=True, order=True)
class Card:
    """一张牌。不可变。

    排序规则：先按 rank 升序（rank 大的牌"大"），rank 相同按 suit 升序。
    注：因为 rank 小的值小，所以"按 rank 升序排序"等于"按牌力降序展示"在
    普通 2..A 的范围内是反的——为符合掼蛋玩家习惯，本类用 rank 升序（2 在前 A 在后）
    的"出牌"序；UI 展示时再 reversed。
    """

    rank: int
    suit: Suit

    def __post_init__(self) -> None:
        if not (
            RANK_2 <= self.rank <= RANK_A
            or self.rank == RANK_SMALL_JOKER
            or self.rank == RANK_BIG_JOKER
        ):
            raise ValueError(f"invalid rank: {self.rank}")

    @property
    def is_joker(self) -> bool:
        return self.suit.is_joker

    @property
    def is_big_joker(self) -> bool:
        return self.suit == Suit.BIG_JOKER

    @property
    def is_small_joker(self) -> bool:
        return self.suit == Suit.SMALL_JOKER

    @property
    def is_normal(self) -> bool:
        """是否是普通牌（2..A），非王。"""
        return NORMAL_MIN <= self.rank <= NORMAL_MAX

    @property
    def short(self) -> str:
        """短文本表示，如 '红桃5' / '大王'。"""
        if self.is_joker:
            return self.suit.cn
        return f"{self.suit.cn}{_RANK_CN[self.rank]}"

    @property
    def compact(self) -> str:
        """紧凑表示，如 '5H' / 'BJ'（Big Joker）。"""
        if self.is_joker:
            return "BJ" if self.is_big_joker else "SJ"
        rank_char = _RANK_CN[self.rank]
        return f"{rank_char}{_SUIT_LETTER[self.suit]}"

    def __str__(self) -> str:
        return self.short


_SUIT_LETTER = {
    Suit.HEARTS: "H",
    Suit.DIAMONDS: "D",
    Suit.SPADES: "S",
    Suit.CLUBS: "C",
}


def make_joker() -> tuple[Card, Card]:
    """构造一对王。"""
    return (
        Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
        Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER),
    )


def card_str(card: Card) -> str:
    return card.short

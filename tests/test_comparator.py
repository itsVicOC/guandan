"""牌型比较测试。"""
from __future__ import annotations

from guandan.engine.card import (
    RANK_2,
    RANK_3,
    RANK_4,
    RANK_5,
    RANK_6,
    RANK_7,
    RANK_8,
    RANK_9,
    RANK_A,
    RANK_BIG_JOKER,
    RANK_SMALL_JOKER,
    Card,
    Suit,
)
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.rules.comparator import (
    can_play,
    compare_bombs,
    compare_same_type,
    is_bomb_type,
)


def c(rank, suit="H"):
    s_map = {"H": Suit.HEARTS, "D": Suit.DIAMONDS, "S": Suit.SPADES, "C": Suit.CLUBS,
             "BJ": Suit.BIG_JOKER, "SJ": Suit.SMALL_JOKER}
    return Card(rank, s_map[suit])


def single(rank):
    return Pattern(PatternType.SINGLE, rank, 1, (c(rank),), 0)


def pair(rank):
    return Pattern(PatternType.PAIR, rank, 1, (c(rank, "H"), c(rank, "D")), 0)


def joker_pair(rank, suit):
    return Pattern(PatternType.PAIR, rank, 1, (c(rank, suit), c(rank, suit)), 0)


def bomb(rank, length=4):
    cards = tuple(c(rank, s) for s in "HDSC"[:length])
    return Pattern(PatternType.BOMB, rank, length, cards, 0)


def four_jokers():
    return Pattern(
        PatternType.FOUR_JOKERS,
        RANK_BIG_JOKER, 4,
        (c(RANK_BIG_JOKER, "BJ"), c(RANK_BIG_JOKER, "BJ"),
         c(RANK_SMALL_JOKER, "SJ"), c(RANK_SMALL_JOKER, "SJ")),
        0,
    )


def straight(rank, length=5):
    return Pattern(PatternType.STRAIGHT, rank, length, (c(RANK_3),) * length, 0)


def straight_flush(rank, length=5):
    return Pattern(
        PatternType.STRAIGHT_FLUSH,
        rank,
        length,
        tuple(c(RANK_3, "H") for _ in range(length)),
        0,
    )


class TestCanPlay:
    def test_first_play_any(self):
        # against=None 时任何牌型都允许
        assert can_play(single(RANK_5), None)
        assert can_play(bomb(RANK_5), None)

    def test_single_press(self):
        assert can_play(single(RANK_7), single(RANK_5))
        assert not can_play(single(RANK_5), single(RANK_7))
        assert not can_play(single(RANK_5), single(RANK_5))

    def test_level_card_press_single(self):
        assert can_play(single(RANK_2), single(RANK_8), level=RANK_2)
        assert not can_play(single(RANK_A), single(RANK_2), level=RANK_2)

    def test_type_mismatch(self):
        # 单张不能压对子
        assert not can_play(single(RANK_A), pair(RANK_5))

    def test_joker_pair_press(self):
        big_pair = joker_pair(RANK_BIG_JOKER, "BJ")
        small_pair = joker_pair(RANK_SMALL_JOKER, "SJ")
        assert can_play(small_pair, pair(RANK_A))
        assert can_play(big_pair, small_pair)
        assert not can_play(pair(RANK_A), small_pair)

    def test_bomb_press_single(self):
        assert can_play(bomb(RANK_5), single(RANK_A))

    def test_bomb_press_pair(self):
        assert can_play(bomb(RANK_7), pair(RANK_A))

    def test_four_jokers_max(self):
        # 四王最大
        assert can_play(four_jokers(), bomb(RANK_A, 4))
        assert can_play(four_jokers(), bomb(RANK_A, 8))

    def test_straight_flush_beats_four_or_same_length_five_bomb(self):
        assert can_play(straight_flush(RANK_9, 5), bomb(RANK_A, 5))
        assert can_play(straight_flush(RANK_9, 5), bomb(RANK_A, 4))
        assert not can_play(straight_flush(RANK_9, 5), bomb(RANK_3, 6))

    def test_no_one_presses_four_jokers(self):
        assert not can_play(bomb(RANK_A, 8), four_jokers())
        assert not can_play(bomb(RANK_A, 4), four_jokers())


class TestCompareSameType:
    def test_straight(self):
        p1 = Pattern(PatternType.STRAIGHT, RANK_8, 5, (c(RANK_4),) * 5, 0)
        p2 = Pattern(PatternType.STRAIGHT, RANK_7, 5, (c(RANK_3),) * 5, 0)
        assert compare_same_type(p1, p2) == 1
        assert compare_same_type(p2, p1) == -1

    def test_level_card_does_not_boost_sequence_rank(self):
        low_wrap = straight(RANK_5)
        high_ace = straight(RANK_A)
        assert compare_same_type(low_wrap, high_ace, level=RANK_5) == -1
        assert not can_play(low_wrap, high_ace, level=RANK_5)


class TestCompareBombs:
    def test_4bomb_vs_4bomb(self):
        # 4 张 5 < 4 张 7
        assert compare_bombs(bomb(RANK_5), bomb(RANK_7)) == -1
        assert compare_bombs(bomb(RANK_7), bomb(RANK_5)) == 1

    def test_4bomb_vs_5bomb(self):
        # 5 张 > 4 张
        assert compare_bombs(bomb(RANK_5, 5), bomb(RANK_7, 4)) == 1
        assert compare_bombs(bomb(RANK_7, 4), bomb(RANK_5, 5)) == -1

    def test_straight_flush_vs_4bomb(self):
        sf = straight_flush(RANK_5, 5)
        b4 = bomb(RANK_A, 4)
        assert compare_bombs(sf, b4) == 1

    def test_four_jokers_max(self):
        # 四王 > 同花顺 > 炸弹
        b5 = bomb(RANK_5, 5)
        sf = Pattern(PatternType.STRAIGHT_FLUSH, RANK_5, 5,
                     (c(RANK_3, "H"), c(RANK_4, "H"), c(RANK_5, "H"),
                      c(RANK_6, "H"), c(RANK_7, "H")), 0)
        assert compare_bombs(four_jokers(), sf) == 1
        assert compare_bombs(four_jokers(), b5) == 1


class TestIsBombType:
    def test_bomb(self):
        assert is_bomb_type(PatternType.BOMB)
        assert is_bomb_type(PatternType.STRAIGHT_FLUSH)
        assert is_bomb_type(PatternType.FOUR_JOKERS)
        assert not is_bomb_type(PatternType.SINGLE)
        assert not is_bomb_type(PatternType.STRAIGHT)

"""牌型识别测试。"""
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
    RANK_10,
    RANK_A,
    RANK_BIG_JOKER,
    RANK_J,
    RANK_K,
    RANK_Q,
    RANK_SMALL_JOKER,
    Suit,
    Card,
)
from guandan.engine.hand import PatternType
from guandan.engine.rules.patterns import (
    detect_patterns,
    find_pattern,
    is_legal,
)


def c(rank, suit="H"):
    s = {"H": Suit.HEARTS, "D": Suit.DIAMONDS, "S": Suit.SPADES, "C": Suit.CLUBS, "BJ": Suit.BIG_JOKER, "SJ": Suit.SMALL_JOKER}[suit]
    return Card(rank, s)


def cards(*specs):
    """从 '5H', 'AS', 'BJ' 这样的规格构造牌。"""
    out = []
    for s in specs:
        if s == "BJ":
            out.append(Card(RANK_BIG_JOKER, Suit.BIG_JOKER))
        elif s == "SJ":
            out.append(Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER))
        else:
            r_char = s[:-1]
            s_char = s[-1]
            rank = {
                "2": RANK_2, "3": RANK_3, "4": RANK_4, "5": RANK_5,
                "6": RANK_6, "7": RANK_7, "8": RANK_8, "9": RANK_9,
                "10": RANK_10, "J": RANK_J, "Q": RANK_Q, "K": RANK_K, "A": RANK_A,
            }[r_char]
            out.append(c(rank, s_char))
    return out


class TestSingle:
    def test_single_normal(self):
        ps = detect_patterns(cards("5H"))
        assert any(p.type == PatternType.SINGLE and p.rank == RANK_5 for p in ps)

    def test_single_ace(self):
        ps = detect_patterns(cards("AS"))
        assert any(p.type == PatternType.SINGLE and p.rank == RANK_A for p in ps)

    def test_single_big_joker(self):
        ps = detect_patterns(cards("BJ"))
        assert any(p.type == PatternType.SINGLE and p.rank == RANK_BIG_JOKER for p in ps)


class TestPair:
    def test_pair(self):
        ps = detect_patterns(cards("5H", "5D"))
        assert any(p.type == PatternType.PAIR and p.rank == RANK_5 for p in ps)

    def test_pair_3_cards(self):
        # 3 张 5 至少能组成 1 对
        ps = detect_patterns(cards("5H", "5D", "5S"))
        pairs = [p for p in ps if p.type == PatternType.PAIR]
        assert len(pairs) >= 1
        assert all(p.rank == RANK_5 for p in pairs)


class TestTriple:
    def test_triple(self):
        ps = detect_patterns(cards("5H", "5D", "5S"))
        assert any(p.type == PatternType.TRIPLE and p.rank == RANK_5 for p in ps)

    def test_triple_4_cards(self):
        ps = detect_patterns(cards("5H", "5D", "5S", "5C"))
        assert any(p.type == PatternType.TRIPLE and p.rank == RANK_5 for p in ps)


class TestTriplePair:
    def test_triple_pair(self):
        ps = detect_patterns(cards("5H", "5D", "5S", "7H", "7D"))
        assert any(p.type == PatternType.TRIPLE_PAIR and p.rank == RANK_5 for p in ps)

    def test_triple_pair_different_ranks(self):
        # 3 张 5 + 2 张 7
        ps = detect_patterns(cards("5H", "5D", "5S", "7H", "7D"))
        tp = [p for p in ps if p.type == PatternType.TRIPLE_PAIR]
        assert any(p.rank == RANK_5 for p in tp)
        # 不能是 3 张 7 + 2 张 5（rank 应是 triple 的 rank）
        assert not any(p.rank == RANK_7 for p in tp)


class TestStraight:
    def test_straight_simple(self):
        # 3-4-5-6-7
        ps = detect_patterns(cards("3H", "4D", "5H", "6S", "7C"))
        assert any(p.type == PatternType.STRAIGHT and p.rank == RANK_7 and p.length == 5 for p in ps)

    def test_straight_high_ace(self):
        # 10-J-Q-K-A
        ps = detect_patterns(cards("10H", "JH", "QH", "KH", "AH"))
        assert any(p.type == PatternType.STRAIGHT and p.rank == RANK_A and p.length == 5 for p in ps)

    def test_straight_low_ace_wrap(self):
        # A-2-3-4-5
        ps = detect_patterns(cards("AH", "2H", "3H", "4H", "5H"))
        assert any(p.type == PatternType.STRAIGHT and p.rank == RANK_5 and p.length == 5 for p in ps)

    def test_straight_2_no_wrap(self):
        # 2-3-4-5-6 非法（2 不在普通顺子中）
        ps = detect_patterns(cards("2H", "3H", "4H", "5H", "6H"))
        assert not any(p.type == PatternType.STRAIGHT for p in ps)

    def test_straight_with_joker(self):
        # 含王非法
        ps = detect_patterns(cards("3H", "4H", "5H", "6H", "BJ"))
        assert not any(p.type == PatternType.STRAIGHT for p in ps)

    def test_straight_too_short(self):
        # 4 张不够
        ps = detect_patterns(cards("3H", "4H", "5H", "6H"))
        assert not any(p.type == PatternType.STRAIGHT for p in ps)

    def test_straight_6_cards(self):
        # 3-4-5-6-7-8
        ps = detect_patterns(cards("3H", "4D", "5S", "6C", "7H", "8D"))
        assert any(p.type == PatternType.STRAIGHT and p.length == 6 and p.rank == RANK_8 for p in ps)


class TestPairSequence:
    def test_pair_sequence_3(self):
        # 33 44 55
        ps = detect_patterns(cards("3H", "3D", "4H", "4D", "5H", "5D"))
        assert any(p.type == PatternType.PAIR_SEQUENCE and p.length == 3 and p.rank == RANK_5 for p in ps)

    def test_pair_sequence_2_invalid(self):
        # 33 44 只有 2 对，非法
        ps = detect_patterns(cards("3H", "3D", "4H", "4D"))
        assert not any(p.type == PatternType.PAIR_SEQUENCE for p in ps)


class TestTripleSequence:
    def test_triple_sequence_2(self):
        # 333 444
        ps = detect_patterns(cards("3H", "3D", "3S", "4H", "4D", "4S"))
        assert any(p.type == PatternType.TRIPLE_SEQUENCE and p.length == 2 and p.rank == RANK_4 for p in ps)


class TestBomb:
    def test_bomb_4(self):
        ps = detect_patterns(cards("5H", "5D", "5S", "5C"))
        assert any(p.type == PatternType.BOMB and p.length == 4 and p.rank == RANK_5 for p in ps)

    def test_bomb_5(self):
        ps = detect_patterns(cards("5H", "5D", "5S", "5C", "5H"))  # 同 rank 最多 4 张
        # 实际游戏中同 rank 最多 4 张，所以 5 张炸弹需要不同 rank... 不，实际游戏中 4-7 张炸弹都是同 rank
        # 2 副牌同 rank 最多 4 张
        # 所以 5 张炸弹 = 2 副牌中 4 张同 rank + 1 wild
        pass  # 跳过，详细测试在 wild 测试

    def test_four_jokers(self):
        ps = detect_patterns(cards("BJ", "BJ", "SJ", "SJ"))
        assert any(p.type == PatternType.FOUR_JOKERS for p in ps)


class TestStraightFlush:
    def test_straight_flush(self):
        ps = detect_patterns(cards("3H", "4H", "5H", "6H", "7H"))
        assert any(p.type == PatternType.STRAIGHT_FLUSH for p in ps)

    def test_not_straight_flush_mixed_suits(self):
        ps = detect_patterns(cards("3H", "4D", "5H", "6H", "7H"))
        assert not any(p.type == PatternType.STRAIGHT_FLUSH for p in ps)


class TestIsLegal:
    def test_legal_single(self):
        assert is_legal(cards("5H"))

    def test_illegal_empty(self):
        assert not is_legal(cards())

    def test_illegal_random(self):
        # 3 5 7 9 散牌
        assert not is_legal(cards("3H", "5H", "7H", "9H"))


class TestFindPattern:
    def test_find_bomb(self):
        p = find_pattern(cards("5H", "5D", "5S", "5C"), PatternType.BOMB)
        assert p is not None
        assert p.type == PatternType.BOMB
        assert p.length == 4

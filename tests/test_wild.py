"""逢人配（Wild Card）相关测试。"""
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
    RANK_J,
    RANK_K,
    RANK_Q,
    Card,
    Suit,
)
from guandan.engine.hand import PatternType
from guandan.engine.rules.patterns import (
    detect_patterns,
    find_complete_pattern,
    has_legal_pattern,
)


def c(rank, suit="H"):
    s_map = {
        "H": Suit.HEARTS, "D": Suit.DIAMONDS,
        "S": Suit.SPADES, "C": Suit.CLUBS,
    }
    return Card(rank, s_map[suit])


# 假设本局打 5，则 5♥ 是逢人配
WILD_5H = c(RANK_5, "H")


class TestWildSingle:
    def test_wild_as_single(self):
        # 5♥ 作单张
        p = find_complete_pattern([WILD_5H], WILD_5H)
        assert p is not None
        assert p.type == PatternType.SINGLE
        assert p.rank == RANK_5
        assert p.wild_used == 1

    def test_wild_substitute_pair(self):
        # 7H + 5♥ (wild) → 对 7
        p = find_complete_pattern([c(RANK_7, "H"), WILD_5H], WILD_5H)
        assert p is not None
        assert p.type == PatternType.PAIR
        assert p.rank == RANK_7
        assert p.wild_used == 1

    def test_wild_substitute_triple(self):
        # 7H 7D + 5♥ → 三张 7
        p = find_complete_pattern([c(RANK_7, "H"), c(RANK_7, "D"), WILD_5H], WILD_5H)
        assert p is not None
        assert p.type == PatternType.TRIPLE
        assert p.rank == RANK_7
        assert p.wild_used == 1


class TestWildBomb:
    def test_wild_bomb_3plus1(self):
        # 3 张 7 + 1 wild → 4 张炸弹
        p = find_complete_pattern(
            [c(RANK_7, "H"), c(RANK_7, "D"), c(RANK_7, "S"), WILD_5H], WILD_5H
        )
        bombs = [x for x in detect_patterns(
            [c(RANK_7, "H"), c(RANK_7, "D"), c(RANK_7, "S"), WILD_5H], WILD_5H
        ) if x.type == PatternType.BOMB]
        assert any(b.rank == RANK_7 and b.wild_used == 1 for b in bombs)

    def test_wild_bomb_2plus2(self):
        # 2 张 7 + 2 wild → 4 张炸弹
        bombs = [x for x in detect_patterns(
            [c(RANK_7, "H"), c(RANK_7, "D"), WILD_5H, WILD_5H], WILD_5H
        ) if x.type == PatternType.BOMB]
        assert any(b.rank == RANK_7 and b.wild_used == 2 for b in bombs)

    def test_wild_bomb_5card(self):
        # 4 张 7 + 1 wild → 5 张炸弹
        bombs = [x for x in detect_patterns(
            [c(RANK_7, "H"), c(RANK_7, "D"), c(RANK_7, "S"), c(RANK_7, "C"), WILD_5H],
            WILD_5H,
        ) if x.type == PatternType.BOMB]
        assert any(b.rank == RANK_7 and b.wild_used == 1 and b.length == 5 for b in bombs)


class TestWildStraight:
    def test_wild_fill_straight(self):
        # 3 4 6 7 + 1 wild → 顺子 3-4-5-6-7
        ps = detect_patterns(
            [c(RANK_3, "H"), c(RANK_4, "D"), c(RANK_6, "S"), c(RANK_7, "C"), WILD_5H],
            WILD_5H,
        )
        straights = [p for p in ps if p.type == PatternType.STRAIGHT]
        assert any(p.length == 5 and p.rank == RANK_7 and p.wild_used == 1 for p in straights)

    def test_wild_fill_ace_low_wrap(self):
        # A 3 4 5 + 1 wild (代 2) → A2345
        ps = detect_patterns(
            [c(RANK_A, "H"), c(RANK_3, "D"), c(RANK_4, "S"), c(RANK_5, "C"), WILD_5H],
            WILD_5H,
        )
        straights = [p for p in ps if p.type == PatternType.STRAIGHT]
        assert any(p.length == 5 and p.rank == RANK_5 and p.wild_used == 1 for p in straights)


class TestWildMultiple:
    def test_two_wilds(self):
        # 2 wilds + 1 张 7 = 三张 7
        ps = detect_patterns(
            [c(RANK_7, "H"), WILD_5H, WILD_5H], WILD_5H
        )
        triples = [p for p in ps if p.type == PatternType.TRIPLE]
        assert any(p.rank == RANK_7 and p.wild_used == 2 for p in triples)


class TestNoWild:
    def test_no_wild_means_normal_play(self):
        # 没有 wild 时 wild_card=None
        ps = detect_patterns([c(RANK_7, "H"), c(RANK_7, "D")], None)
        pairs = [p for p in ps if p.type == PatternType.PAIR]
        assert len(pairs) == 1
        assert pairs[0].wild_used == 0


class TestHasLegalPattern:
    def test_has_pattern(self):
        # 1 张牌是合法单张
        assert has_legal_pattern([c(RANK_5, "H")], None)

    def test_has_pair(self):
        # 2 张同点是合法对子
        assert has_legal_pattern([c(RANK_5, "H"), c(RANK_5, "D")], None)

    def test_each_card_alone_is_legal(self):
        # 4 张散牌每张都是单张，所以 has_legal_pattern 返回 True
        assert has_legal_pattern(
            [c(RANK_3, "H"), c(RANK_5, "H"), c(RANK_7, "H"), c(RANK_9, "H")], None
        )

    def test_empty(self):
        # 空集合不是合法牌型
        assert not has_legal_pattern([], None)

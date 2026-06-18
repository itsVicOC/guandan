"""Property-based testing：牌型识别 / 比较的随机性质验证。"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from guandan.engine.card import (
    RANK_2,
    RANK_A,
    RANK_BIG_JOKER,
    RANK_SMALL_JOKER,
    Card,
    Suit,
)
from guandan.engine.deck import make_deck
from guandan.engine.hand import PatternType
from guandan.engine.rules.patterns import (
    detect_patterns,
    find_complete_pattern,
    has_legal_pattern,
)

# 测试用 suit 列表
SUITS_NORMAL = [Suit.HEARTS, Suit.DIAMONDS, Suit.SPADES, Suit.CLUBS]
RANKS = list(range(RANK_2, RANK_A + 1))


@st.composite
def single_cards(draw, min_rank=RANK_2, max_rank=RANK_A):
    r = draw(st.integers(min_value=min_rank, max_value=max_rank))
    s = draw(st.sampled_from(SUITS_NORMAL))
    return Card(r, s)


@st.composite
def card_lists(draw, min_size=1, max_size=10, allow_jokers=True):
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    cards = []
    for _ in range(n):
        if allow_jokers and draw(st.booleans()):
            # 王
            j = draw(st.sampled_from([RANK_BIG_JOKER, RANK_SMALL_JOKER]))
            cards.append(Card(j, Suit.SMALL_JOKER if j == RANK_SMALL_JOKER else Suit.BIG_JOKER))
        else:
            r = draw(st.integers(min_value=RANK_2, max_value=RANK_A))
            s = draw(st.sampled_from(SUITS_NORMAL))
            cards.append(Card(r, s))
    return cards


class TestPatternProperties:
    @given(card_lists(min_size=1, max_size=8))
    @settings(max_examples=200)
    def test_single_card_is_legal(self, cards):
        """任何 1 张牌都应是合法单张。"""
        c = cards[0]
        ps = detect_patterns([c], None)
        singles = [p for p in ps if p.type == PatternType.SINGLE]
        assert any(p.rank == c.rank for p in singles)

    @given(st.lists(single_cards(), min_size=4, max_size=4))
    @settings(max_examples=100)
    def test_same_rank_4_is_bomb(self, cards):
        """任意 4 张同 rank 必是炸弹。"""
        if len({c.rank for c in cards}) != 1:
            return  # 不是同 rank，跳过
        ps = detect_patterns(cards, None)
        bombs = [p for p in ps if p.type == PatternType.BOMB]
        assert any(b.length == 4 and b.rank == cards[0].rank for b in bombs)

    @given(st.lists(single_cards(min_rank=3, max_rank=RANK_A), min_size=5, max_size=10))
    @settings(max_examples=100)
    def test_consecutive_cards_may_be_straight(self, cards):
        """去重后含 5 张连续 rank 应能识别为固定 5 张顺子。"""
        ranks = sorted({c.rank for c in cards})
        if len(ranks) < 5:
            return
        # 找最长连续段
        longest = 1
        cur = 1
        for i in range(1, len(ranks)):
            if ranks[i] == ranks[i - 1] + 1:
                cur += 1
                longest = max(longest, cur)
            else:
                cur = 1
        if longest < 5:
            return
        # 构造一个固定 5 张连续段
        start = None
        for i in range(len(ranks) - 4):
            if ranks[i + 4] - ranks[i] == 4:
                start = i
                break
        if start is None:
            return
        window = ranks[start : start + 5]
        # 取每种 rank 一张牌
        used = []
        for r in window:
            for c in cards:
                if c.rank == r and c not in used:
                    used.append(c)
                    break
        if len(used) != 5:
            return
        ps = detect_patterns(used, None)
        straights = [p for p in ps if p.type == PatternType.STRAIGHT]
        # 至少一个固定 5 张顺子
        assert any(p.length == 5 for p in straights), (
            f"Failed for ranks={window}, got {[p.length for p in straights]}"
        )


class TestHasLegalPattern:
    @given(card_lists(min_size=0, max_size=0))
    def test_empty(self, cards):
        assert not has_legal_pattern([], None)

    @given(card_lists(min_size=1, max_size=1))
    def test_one_card(self, cards):
        assert has_legal_pattern(cards, None)


class TestFindCompletePattern:
    @given(st.tuples(single_cards(), single_cards()))
    @settings(max_examples=100)
    def test_pair_of_same_rank(self, pair):
        c1, c2 = pair
        # 强制 rank 相同
        c2 = Card(c1.rank, c2.suit)
        p = find_complete_pattern([c1, c2], None)
        assert p is not None
        # 至少返回一个 PAIR 类型的合法牌型
        ps = [pp for pp in detect_patterns([c1, c2], None) if pp.type == PatternType.PAIR]
        assert any(pp.rank == c1.rank for pp in ps)

    @given(st.tuples(single_cards(), single_cards(), single_cards()))
    @settings(max_examples=100)
    def test_triple_of_same_rank(self, triple):
        c1, c2, c3 = triple
        # 强制同 rank
        c2 = Card(c1.rank, c2.suit)
        c3 = Card(c1.rank, c3.suit)
        ps = [pp for pp in detect_patterns([c1, c2, c3], None) if pp.type == PatternType.TRIPLE]
        assert any(pp.rank == c1.rank for pp in ps)


class TestDeck:
    def test_deck_has_108_unique_cards(self):
        deck = make_deck()
        assert len(deck) == 108
        # 2 副牌所以每张牌有 2 张
        from collections import Counter

        cnt = Counter(deck)
        assert all(v == 2 for v in cnt.values())

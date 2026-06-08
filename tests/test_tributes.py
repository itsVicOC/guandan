"""进贡 / 还贡 / 抗贡测试。"""
from __future__ import annotations

from guandan.engine.card import (
    RANK_2,
    RANK_5,
    RANK_7,
    RANK_10,
    RANK_A,
    RANK_BIG_JOKER,
    RANK_K,
    RANK_SMALL_JOKER,
    Card,
    Suit,
)
from guandan.engine.rules.tributes import (
    can_resist_tribute,
    can_return_tribute,
    resolve_tribute,
    select_return_card,
    select_tribute_card,
)


def c(rank, suit="H"):
    s_map = {"H": Suit.HEARTS, "D": Suit.DIAMONDS, "S": Suit.SPADES, "C": Suit.CLUBS,
             "BJ": Suit.BIG_JOKER, "SJ": Suit.SMALL_JOKER}
    return Card(rank, s_map[suit])


class TestCanResistTribute:
    def test_resist_with_four_jokers(self):
        hand = [c(RANK_BIG_JOKER, "BJ"), c(RANK_BIG_JOKER, "BJ"),
                c(RANK_SMALL_JOKER, "SJ"), c(RANK_SMALL_JOKER, "SJ"),
                c(RANK_5)]
        assert can_resist_tribute(hand)

    def test_no_resist_with_two_big_only(self):
        hand = [c(RANK_BIG_JOKER, "BJ"), c(RANK_BIG_JOKER, "BJ"),
                c(RANK_5)]
        assert not can_resist_tribute(hand)


class TestSelectTributeCard:
    def test_max_card(self):
        hand = [c(RANK_5), c(RANK_A), c(RANK_K)]
        assert select_tribute_card(hand) == c(RANK_A)

    def test_joker_max(self):
        hand = [c(RANK_A), c(RANK_BIG_JOKER, "BJ")]
        assert select_tribute_card(hand) == c(RANK_BIG_JOKER, "BJ")


class TestCanReturnTribute:
    def test_low_card(self):
        assert can_return_tribute(c(RANK_5))
        assert can_return_tribute(c(RANK_10))
        assert not can_return_tribute(c(RANK_K))
        assert not can_return_tribute(c(RANK_BIG_JOKER, "BJ"))


class TestSelectReturnCard:
    def test_selects_lowest(self):
        hand = [c(RANK_5), c(RANK_7), c(RANK_K), c(RANK_2)]
        assert select_return_card(hand) == c(RANK_2)

    def test_excludes_jokers(self):
        hand = [c(RANK_BIG_JOKER, "BJ"), c(RANK_5)]
        # 不能还王，所以选 5
        assert select_return_card(hand) == c(RANK_5)


class TestResolveTribute:
    def test_normal_flow(self):
        upstream_hand = [c(RANK_5), c(RANK_7), c(RANK_A)]
        downstream_hand = [c(RANK_2), c(RANK_K), c(RANK_A)]
        result = resolve_tribute(
            upstream=0, downstream=1,
            upstream_hand=upstream_hand,
            downstream_hand=downstream_hand,
        )
        assert not result.resisted
        assert result.tribute_card == c(RANK_A)  # 下游最大
        # 还贡：upstream 收到 A 后还 ≤10 的最小
        assert result.return_card == c(RANK_5)
        # 进 / 还贡后从进贡方起牌
        assert result.first_player_after == 1

    def test_resist_flow(self):
        upstream_hand = [c(RANK_5), c(RANK_7)]
        downstream_hand = [
            c(RANK_BIG_JOKER, "BJ"), c(RANK_BIG_JOKER, "BJ"),
            c(RANK_SMALL_JOKER, "SJ"), c(RANK_SMALL_JOKER, "SJ"),
            c(RANK_5),
        ]
        result = resolve_tribute(
            upstream=0, downstream=1,
            upstream_hand=upstream_hand,
            downstream_hand=downstream_hand,
        )
        assert result.resisted
        assert result.tribute_card is None
        assert result.return_card is None

"""进贡 / 还贡 / 抗贡测试。"""
from __future__ import annotations

from guandan.engine.card import (
    RANK_2,
    RANK_3,
    RANK_4,
    RANK_5,
    RANK_7,
    RANK_8,
    RANK_9,
    RANK_10,
    RANK_A,
    RANK_BIG_JOKER,
    RANK_K,
    RANK_SMALL_JOKER,
    Card,
    Suit,
)
from guandan.engine.rules.tributes import (
    apply_tribute_flow,
    can_resist_tribute,
    can_return_tribute,
    next_round_first_player_after_tribute,
    resolve_tribute,
    select_return_card,
    select_tribute_card,
)


def c(rank, suit="H"):
    s_map = {"H": Suit.HEARTS, "D": Suit.DIAMONDS, "S": Suit.SPADES, "C": Suit.CLUBS,
             "BJ": Suit.BIG_JOKER, "SJ": Suit.SMALL_JOKER}
    return Card(rank, s_map[suit])


class TestCanResistTribute:
    def test_resist_with_two_big_jokers(self):
        hand = [c(RANK_BIG_JOKER, "BJ"), c(RANK_BIG_JOKER, "BJ"),
                c(RANK_5)]
        assert can_resist_tribute(hand)

    def test_no_resist_with_one_big(self):
        hand = [c(RANK_BIG_JOKER, "BJ"),
                c(RANK_5)]
        assert not can_resist_tribute(hand)


class TestSelectTributeCard:
    def test_max_card(self):
        hand = [c(RANK_5), c(RANK_A), c(RANK_K)]
        assert select_tribute_card(hand) == c(RANK_A)

    def test_joker_max(self):
        hand = [c(RANK_A), c(RANK_BIG_JOKER, "BJ")]
        assert select_tribute_card(hand) == c(RANK_BIG_JOKER, "BJ")

    def test_level_card_is_stronger_than_ace_for_tribute(self):
        hand = [c(RANK_5, "D"), c(RANK_A), c(RANK_K)]

        assert select_tribute_card(hand, level=RANK_5) == c(RANK_5, "D")

    def test_red_heart_level_card_is_excluded_from_tribute(self):
        wild = c(RANK_5, "H")
        hand = [wild, c(RANK_A), c(RANK_K)]

        assert select_tribute_card(hand, wild_card=wild, level=RANK_5) == c(RANK_A)


class TestNextRoundFirstPlayer:
    def test_last_player_starts_when_third_and_last_are_different_teams(self):
        finish_order = [0, 1, 2]  # 三游西，末游北，不同队
        hands = [[c(RANK_2)], [c(RANK_A)], [c(RANK_2)], [c(RANK_5)]]

        assert next_round_first_player_after_tribute(finish_order, hands) == 3

    def test_larger_tribute_starts_when_third_and_last_are_same_team(self):
        finish_order = [0, 2, 1]  # 三游南，末游北，同为下游方
        hands = [
            [c(RANK_2)],
            [c(RANK_A)],
            [c(RANK_2)],
            [c(RANK_K)],
        ]

        assert next_round_first_player_after_tribute(finish_order, hands) == 1

    def test_clockwise_player_starts_when_double_tribute_same_rank(self):
        finish_order = [0, 2, 1]  # 三游南，末游北，同为下游方
        hands = [
            [c(RANK_2)],
            [c(RANK_A, "D")],
            [c(RANK_2)],
            [c(RANK_A, "S")],
        ]

        assert next_round_first_player_after_tribute(finish_order, hands) == 1


class TestCanReturnTribute:
    def test_low_card(self):
        assert can_return_tribute(c(RANK_5))
        assert can_return_tribute(c(RANK_10))
        assert not can_return_tribute(c(RANK_K))
        assert not can_return_tribute(c(RANK_BIG_JOKER, "BJ"))

    def test_cannot_return_level_card(self):
        assert not can_return_tribute(c(RANK_5), level=RANK_5)


class TestSelectReturnCard:
    def test_selects_lowest(self):
        hand = [c(RANK_5), c(RANK_7), c(RANK_K), c(RANK_2)]
        assert select_return_card(hand) == c(RANK_2)

    def test_excludes_jokers(self):
        hand = [c(RANK_BIG_JOKER, "BJ"), c(RANK_5)]
        # 不能还王，所以选 5
        assert select_return_card(hand) == c(RANK_5)

    def test_raises_when_no_legal_return_card(self):
        hand = [c(RANK_BIG_JOKER, "BJ"), c(RANK_A), c(RANK_5)]
        import pytest

        with pytest.raises(ValueError, match="no legal return tribute card"):
            select_return_card(hand, level=RANK_5)


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
        assert result.first_player_after == 0


class TestApplyTributeFlow:
    def test_single_tribute_moves_cards_and_returns_non_level_low_card(self):
        wild = c(RANK_5, "H")
        hands = [
            [c(RANK_3), c(RANK_8)],
            [c(RANK_2)],
            [c(RANK_4)],
            [wild, c(RANK_A), c(RANK_7)],
        ]
        result = apply_tribute_flow(
            [0, 1, 2],
            hands,
            level=RANK_5,
            wild_card=wild,
        )

        assert result.first_player == 3
        assert not result.resisted
        assert c(RANK_A) in hands[0]
        assert c(RANK_3) in hands[3]
        assert wild in hands[3]
        assert c(RANK_A) not in hands[3]
        assert c(RANK_3) not in hands[0]

    def test_single_tribute_excludes_wild_card(self):
        wild = c(RANK_5, "H")
        hands = [
            [c(RANK_3)],
            [c(RANK_2)],
            [c(RANK_4)],
            [wild, c(RANK_K)],
        ]
        result = apply_tribute_flow([0, 1, 2], hands, level=RANK_5, wild_card=wild)

        assert result.exchanges[0].tribute_card == c(RANK_K)
        assert result.first_player == 3

    def test_double_tribute_assigns_large_to_head_small_to_second(self):
        hands = [
            [c(RANK_3), c(RANK_8)],
            [c(RANK_4), c(RANK_9)],
            [c(RANK_2)],
            [c(RANK_A), c(RANK_7)],
        ]
        result = apply_tribute_flow([0, 2, 1], hands, level=RANK_5, wild_card=None)

        assert result.first_player == 3
        assert c(RANK_A) in hands[0]
        assert c(RANK_9) in hands[2]
        assert c(RANK_3) in hands[3]
        assert c(RANK_4) in hands[1]

    def test_double_tribute_resists_with_two_big_jokers_across_team(self):
        hands = [
            [c(RANK_3)],
            [c(RANK_BIG_JOKER, "BJ")],
            [c(RANK_4)],
            [c(RANK_BIG_JOKER, "BJ")],
        ]
        result = apply_tribute_flow([0, 2, 1], hands, level=RANK_5, wild_card=None)

        assert result.resisted
        assert result.first_player == 0
        assert result.exchanges == []

    def test_double_tribute_same_rank_uses_clockwise_assignment(self):
        hands = [
            [c(RANK_3), c(RANK_8)],
            [c(RANK_A, "D"), c(RANK_4)],
            [c(RANK_4), c(RANK_9)],
            [c(RANK_A, "S"), c(RANK_7)],
        ]

        result = apply_tribute_flow([0, 2, 1], hands, level=RANK_5, wild_card=None)

        assert result.first_player == 1
        assert result.exchanges[0].from_player == 1
        assert result.exchanges[0].to_player == 0
        assert c(RANK_A, "D") in hands[0]
        assert c(RANK_A, "S") in hands[2]

    def test_double_tribute_level_card_beats_ace(self):
        hands = [
            [c(RANK_3), c(RANK_8)],
            [c(RANK_A), c(RANK_4)],
            [c(RANK_4), c(RANK_9)],
            [c(RANK_5, "D"), c(RANK_7)],
        ]

        result = apply_tribute_flow([0, 2, 1], hands, level=RANK_5, wild_card=c(RANK_5, "H"))

        assert result.first_player == 3
        assert result.exchanges[0].from_player == 3
        assert c(RANK_5, "D") in hands[0]

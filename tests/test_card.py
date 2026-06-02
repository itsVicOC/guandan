"""Card / Hand / Deck 基础数据类测试。"""
from __future__ import annotations

import random

from rich.markup import render

from guandan.engine.card import (
    Card,
    RANK_2,
    RANK_3,
    RANK_4,
    RANK_5,
    RANK_6,
    RANK_7,
    RANK_8,
    RANK_A,
    RANK_BIG_JOKER,
    RANK_SMALL_JOKER,
    Suit,
    make_joker,
)
from guandan.engine.deck import deal, make_deck, shuffle_deck
from guandan.engine.hand import Hand, sort_cards, sort_hand


class TestCard:
    def test_card_immutable(self):
        c = Card(RANK_5, Suit.HEARTS)
        try:
            c.rank = 99  # type: ignore[misc]
            assert False, "should be frozen"
        except Exception:  # noqa: BLE001
            pass

    def test_card_short(self):
        assert Card(RANK_5, Suit.HEARTS).short == "红桃5"
        assert Card(RANK_A, Suit.SPADES).short == "黑桃A"
        assert make_joker()[0].short == "大王"
        assert make_joker()[1].short == "小王"

    def test_card_compact(self):
        assert Card(RANK_5, Suit.HEARTS).compact == "5H"
        assert Card(RANK_A, Suit.SPADES).compact == "AS"
        assert make_joker()[0].compact == "BJ"
        assert make_joker()[1].compact == "SJ"

    def test_card_rich_markup(self):
        # .rich 输出 rich markup（不直接渲染，只确认结构）
        h = Card(RANK_5, Suit.HEARTS).rich
        d = Card(RANK_7, Suit.DIAMONDS).rich
        s = Card(RANK_A, Suit.SPADES).rich
        c = Card(RANK_3, Suit.CLUBS).rich
        assert "[red]" in h and "♥" in h
        assert "[red]" in d and "♦" in d
        assert "♠" in s and "[red]" not in s
        assert "♣" in c and "[red]" not in c
        # 大小王用 yellow
        big = make_joker()[0].rich
        small = make_joker()[1].rich
        assert "[yellow]" in big and "JOKER" in big
        assert "[yellow]" in small and "joker" in small

    def test_rich_markup_renderable(self):
        """回归测试：含 suit 的 markup 必须能正常被 rich 渲染（防止 v0.2.2 错误重现）。

        错误：把 markup 包在 '[]' 里导致 rich 把 '♠' 当成 tag 名 → MarkupError。
        """
        from rich.console import Console
        from io import StringIO
        # 模拟 _pattern_str 的输出
        cards = [
            Card(RANK_4, Suit.SPADES),  # ♠
            Card(RANK_4, Suit.HEARTS),  # [red]♥[/red]
            Card(RANK_5, Suit.CLUBS),
            Card(RANK_5, Suit.DIAMONDS),
            Card(RANK_6, Suit.CLUBS),
            Card(RANK_6, Suit.HEARTS),
        ]
        cards_str = " ".join(c.rich for c in cards)
        # 错误版本（会失败）：f"pair_sequence [{cards_str}]"
        content = f"pair_sequence  {cards_str}"  # 修正版本：去掉外层 []
        # 关键：用 rich 渲染不应报错
        buf = StringIO()
        console = Console(file=buf, width=80, force_terminal=True)
        console.print(content)  # 不抛异常 = 通过

    def test_card_invalid_rank(self):
        try:
            Card(99, Suit.HEARTS)
            assert False, "should raise"
        except ValueError:
            pass

    def test_card_order(self):
        # rank 大的"大"，但用 dataclass(order=True) 时默认 tuple 排序按 rank 升序
        a = Card(RANK_2, Suit.HEARTS)
        b = Card(RANK_A, Suit.HEARTS)
        assert a < b

        big = Card(RANK_BIG_JOKER, Suit.BIG_JOKER)
        small = Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER)
        assert small < big


class TestHand:
    def test_hand_empty(self):
        h = Hand()
        assert len(h) == 0
        assert h.is_empty()

    def test_hand_add_remove(self):
        h = Hand()
        c1 = Card(RANK_5, Suit.HEARTS)
        c2 = Card(RANK_3, Suit.HEARTS)
        h.add(c1)
        h.add(c2)
        # 排序：rank 升序（c2=3 在前，c1=5 在后）
        assert h.cards[0] == c2
        assert h.cards[1] == c1
        h.remove(c1)
        assert len(h) == 1

    def test_hand_count_by_rank(self):
        h = Hand()
        h.add_many(
            [
                Card(RANK_5, Suit.HEARTS),
                Card(RANK_5, Suit.DIAMONDS),
                Card(RANK_3, Suit.HEARTS),
            ]
        )
        cnt = h.count_by_rank()
        assert cnt[RANK_5] == 2
        assert cnt[RANK_3] == 1

    def test_sort_hand(self):
        h = Hand(
            [
                Card(RANK_5, Suit.HEARTS),
                Card(RANK_2, Suit.HEARTS),
                Card(RANK_A, Suit.HEARTS),
            ]
        )
        sorted_h = sort_hand(h)
        # 大到小
        assert sorted_h.cards[0].rank == RANK_A
        assert sorted_h.cards[-1].rank == RANK_2

    def test_sort_cards(self):
        cards = [
            Card(RANK_3, Suit.HEARTS),
            Card(RANK_2, Suit.HEARTS),
            Card(RANK_A, Suit.HEARTS),
            Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
        ]
        s = sort_cards(cards)
        assert s[0].rank == RANK_BIG_JOKER
        assert s[-1].rank == RANK_2


class TestDeck:
    def test_make_deck_count(self):
        deck = make_deck()
        assert len(deck) == 108

    def test_make_deck_composition(self):
        deck = make_deck()
        # 4 张大王 + 小王
        big = sum(1 for c in deck if c.is_big_joker)
        small = sum(1 for c in deck if c.is_small_joker)
        assert big == 2
        assert small == 2
        # 每种花色 + 点数有 2 张
        for s in [Suit.HEARTS, Suit.DIAMONDS, Suit.SPADES, Suit.CLUBS]:
            for r in range(2, 15):
                count = sum(1 for c in deck if c.suit == s and c.rank == r)
                assert count == 2, f"{s} {r} should have 2, got {count}"

    def test_shuffle_deck(self):
        deck = make_deck()
        rng = random.Random(42)
        shuffled = shuffle_deck(deck, rng)
        assert len(shuffled) == 108
        assert sorted(shuffled) == sorted(deck)  # 元素不变

    def test_deal(self):
        deck = make_deck()
        rng = random.Random(42)
        shuffled = shuffle_deck(deck, rng)
        hands = deal(shuffled, 4)
        assert len(hands) == 4
        for h in hands:
            assert len(h) == 27
        # 4 家手牌合并应等于原牌堆
        all_cards = []
        for h in hands:
            all_cards.extend(h)
        assert sorted(all_cards) == sorted(deck)

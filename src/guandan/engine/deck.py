"""牌堆（Deck）：生成 108 张、洗牌、发牌。"""
from __future__ import annotations

import random
from collections.abc import Sequence

from .card import (
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
    Card,
    Suit,
)


def make_deck() -> list[Card]:
    """生成 2 副标准扑克的 108 张牌。

    - 4 种花色 × 13 个点数（2..A）× 2 副 = 104
    - + 2 张小王 + 2 张大王 = 4
    - 总计 108 张
    """
    deck: list[Card] = []
    ranks = [
        RANK_2,
        RANK_3,
        RANK_4,
        RANK_5,
        RANK_6,
        RANK_7,
        RANK_8,
        RANK_9,
        RANK_10,
        RANK_J,
        RANK_Q,
        RANK_K,
        RANK_A,
    ]
    suits = [Suit.HEARTS, Suit.DIAMONDS, Suit.SPADES, Suit.CLUBS]
    for _deck_idx in range(2):
        for s in suits:
            for r in ranks:
                deck.append(Card(r, s))
    # 4 张王
    deck.append(Card(RANK_BIG_JOKER, Suit.BIG_JOKER))
    deck.append(Card(RANK_BIG_JOKER, Suit.BIG_JOKER))
    deck.append(Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER))
    deck.append(Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER))
    return deck


def shuffle_deck(deck: Sequence[Card], rng: random.Random) -> list[Card]:
    """洗牌。返回新列表。"""
    out = list(deck)
    rng.shuffle(out)
    return out


def deal(deck: Sequence[Card], num_players: int = 4) -> list[list[Card]]:
    """发牌。每人 27 张（108/4），无底牌。"""
    assert len(deck) == 108, f"deck should have 108 cards, got {len(deck)}"
    assert len(deck) % num_players == 0, "deck size must divide evenly"
    per_player = len(deck) // num_players
    return [list(deck[i * per_player : (i + 1) * per_player]) for i in range(num_players)]

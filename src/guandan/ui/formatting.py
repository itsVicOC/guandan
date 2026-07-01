"""Display helpers shared by GUI/TUI-adjacent controllers."""
from __future__ import annotations

from collections.abc import Sequence

from ..engine.card import Card, Suit
from ..engine.hand import Pattern, PatternType, comparison_rank


def rank_label(card: Card) -> str:
    return rank_value_label(card.rank)


def rank_value_label(rank: int) -> str:
    if rank == 101:
        return "大王"
    if rank == 100:
        return "小王"
    if rank == 14:
        return "A"
    if rank == 13:
        return "K"
    if rank == 12:
        return "Q"
    if rank == 11:
        return "J"
    return str(rank)


def suit_short_label(suit: Suit) -> str:
    return {
        Suit.HEARTS: "红",
        Suit.DIAMONDS: "方",
        Suit.SPADES: "黑",
        Suit.CLUBS: "梅",
        Suit.BIG_JOKER: "大",
        Suit.SMALL_JOKER: "小",
    }[suit]


def suit_symbol_plain(suit: Suit) -> str:
    return {
        Suit.HEARTS: "♥",
        Suit.DIAMONDS: "♦",
        Suit.SPADES: "♠",
        Suit.CLUBS: "♣",
        Suit.BIG_JOKER: "JOKER",
        Suit.SMALL_JOKER: "joker",
    }[suit]


def card_label(card: Card, *, include_symbol: bool = True) -> str:
    if card.is_big_joker:
        return "大王"
    if card.is_small_joker:
        return "小王"
    if include_symbol:
        return f"{suit_short_label(card.suit)}{rank_label(card)}{suit_symbol_plain(card.suit)}"
    return f"{suit_short_label(card.suit)}{rank_label(card)}"


def cards_text(cards: Sequence[Card]) -> str:
    return " ".join(card_label(card, include_symbol=False) for card in cards)


def pattern_type_label(pattern_type: PatternType) -> str:
    return {
        PatternType.SINGLE: "单张",
        PatternType.PAIR: "对子",
        PatternType.TRIPLE: "三张",
        PatternType.TRIPLE_PAIR: "三带二",
        PatternType.STRAIGHT: "顺子",
        PatternType.PAIR_SEQUENCE: "连对",
        PatternType.TRIPLE_SEQUENCE: "钢板",
        PatternType.BOMB: "炸弹",
        PatternType.STRAIGHT_FLUSH: "同花顺",
        PatternType.FOUR_JOKERS: "四王炸",
    }[pattern_type]


def pattern_summary(pattern: Pattern, level: int) -> str:
    base_rank = rank_value_label(pattern.rank)
    effective = comparison_rank(pattern, level)
    rank_text = f"{base_rank}(级牌)" if effective != pattern.rank else base_rank
    return (
        f"{pattern_type_label(pattern.type)} · 主牌 {rank_text} · "
        f"张数 {len(pattern.cards)} · [{cards_text(pattern.cards)}]"
    )


def play_rejection_message(
    selected: Sequence[Card],
    pattern: Pattern,
    table_top: Pattern,
    level: int,
) -> str:
    return (
        "不能压过桌面："
        f"你选 [{cards_text(selected)}]，识别为 {pattern_summary(pattern, level)}；"
        f"桌面最大为 {pattern_summary(table_top, level)}；"
        f"当前级牌 {rank_value_label(level)} 参与单/对/三/三带二/炸弹点数比较"
    )


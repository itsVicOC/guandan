"""进贡 / 还贡 / 抗贡。

流程：
1. 触发条件：非首局发牌后，按上一局名次执行进贡 / 还贡。
2. 进贡方选择手牌中最大的单牌，排除本局红心级牌。
3. 收贡方还一张点数 ≤ 10、非级牌、非王的牌。
4. 抗贡：单贡方自己有 2 张大王，或双贡方合计有 2 张大王。
5. 单贡由末游先手；双贡由进贡给头游者先手；抗贡由上一局头游先手。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import List, Optional

from ..card import RANK_10, RANK_A, Card
from ..events import Event, TributeResisted, TributeReturned, TributeSent


def can_resist_tribute(hand: List[Card]) -> bool:
    """兼容旧接口：单人是否可抗贡（手牌含 2 张大王）。"""
    big = sum(1 for c in hand if c.is_big_joker)
    return big >= 2


def _is_wild(card: Card, wild_card: Card | None) -> bool:
    return wild_card is not None and card == wild_card


def _tribute_strength(card: Card, level: int | None = None) -> int:
    if card.is_joker:
        return card.rank
    if level is not None and card.rank == level:
        return RANK_A + 1
    return card.rank


def _tribute_sort_key(card: Card, level: int | None = None) -> tuple[int, int]:
    return (_tribute_strength(card, level), -int(card.suit))


def select_tribute_card(
    hand: List[Card], wild_card: Card | None = None, level: int | None = None
) -> Card:
    """选择进贡牌：除本局红心级牌外，按本局牌力取最大单牌。"""
    candidates = [card for card in hand if not _is_wild(card, wild_card)]
    if not candidates:
        candidates = list(hand)
    return max(candidates, key=lambda card: _tribute_sort_key(card, level))


def legal_tribute_cards(
    hand: List[Card], wild_card: Card | None = None, level: int | None = None
) -> list[Card]:
    """Return every physically distinct maximum card that may be paid as tribute."""
    candidates = [card for card in hand if not _is_wild(card, wild_card)]
    if not candidates:
        candidates = list(hand)
    if not candidates:
        return []
    maximum = max(_tribute_strength(card, level) for card in candidates)
    return [card for card in candidates if _tribute_strength(card, level) == maximum]


def compare_tribute_cards(
    left: Card, right: Card, *, level: int | None = None, same_rank_ties: bool = False
) -> int:
    """比较两张进贡牌大小。

    返回 1 表示 left 大，-1 表示 right 大，0 表示同等。双贡分配时
    `same_rank_ties=True`，同点数即视为平局，由顺时针规则决定给头游的一方。
    """
    if same_rank_ties and left.rank == right.rank:
        return 0
    left_key = _tribute_sort_key(left, level)
    right_key = _tribute_sort_key(right, level)
    if left_key > right_key:
        return 1
    if left_key < right_key:
        return -1
    return 0


def can_return_tribute(card: Card, level: int | None = None) -> bool:
    """检查一张牌是否可以作为还贡（≤10、非王、非级牌）。"""
    if card.is_joker:
        return False
    if level is not None and card.rank == level:
        return False
    return card.rank <= RANK_10


def select_return_card(hand: List[Card], level: int | None = None) -> Card:
    """选择还贡牌：符合规则的最小牌。

    若没有 ≤10、非王、非级牌的合法还贡牌，显式抛错。正常发牌状态下
    极少出现这种手牌；抛错比静默还出非法牌更利于定位规则状态异常。
    """
    candidates = [c for c in hand if can_return_tribute(c, level)]
    if not candidates:
        raise ValueError("no legal return tribute card")
    return min(candidates)


def legal_return_cards(hand: List[Card], level: int | None = None) -> list[Card]:
    """Return all cards that may legally be used for the return tribute."""
    return [card for card in hand if can_return_tribute(card, level)]


@dataclass
class TributeResult:
    """进贡/还贡结果。"""

    resisted: bool
    tribute_card: Optional[Card]  # 进贡的牌
    return_card: Optional[Card]  # 还贡的牌
    first_player_after: int  # 进 / 还贡后下一轮先手


@dataclass
class TributeExchange:
    """单次进贡与对应还贡。"""

    from_player: int
    to_player: int
    tribute_card: Card
    return_card: Optional[Card] = None


@dataclass
class TributeFlowResult:
    """新局进贡流程结果。"""

    first_player: int
    resisted: bool
    exchanges: list[TributeExchange]
    events: list[Event]


def next_round_first_player_after_tribute(
    finish_order: list[int],
    next_hands: list[list[Card]],
    wild_card: Card | None = None,
    level: int | None = None,
) -> int:
    """根据上局名次和新局进贡牌确定下一局先手。

    - 三游和末游不同队：末游单贡，末游先手。
    - 三游和末游同队：三游、末游双贡，比较两人的进贡牌，贡大者先手。
    - 进贡牌同点数时，按头游顺时针方向先遇到的进贡方先手。
    """
    if len(finish_order) < 3:
        return finish_order[0] if finish_order else 0

    head = finish_order[0]
    third = finish_order[2]
    last = next(player for player in range(4) if player not in finish_order)
    if third % 2 != last % 2:
        return last
    if len(next_hands) <= max(third, last) or not next_hands[third] or not next_hands[last]:
        return last

    third_tribute = select_tribute_card(next_hands[third], wild_card, level)
    last_tribute = select_tribute_card(next_hands[last], wild_card, level)
    comparison = compare_tribute_cards(
        third_tribute, last_tribute, level=level, same_rank_ties=True
    )
    if comparison > 0:
        return third
    if comparison < 0:
        return last
    cursor = _clockwise_next(head)
    while cursor not in (third, last):
        cursor = _clockwise_next(cursor)
    return cursor


def _last_player(finish_order: list[int]) -> int:
    return next(player for player in range(4) if player not in finish_order)


def _clockwise_next(player: int) -> int:
    return (player + 1) % 4


def _tribute_team_has_two_big_jokers(
    hands: list[list[Card]], players: list[int]
) -> bool:
    return sum(1 for player in players for card in hands[player] if card.is_big_joker) >= 2


def apply_tribute_flow(
    finish_order: list[int],
    hands: list[list[Card]],
    *,
    level: int,
    wild_card: Card | None,
    tribute_choices: Mapping[int, Card] | None = None,
    return_choices: Mapping[int, Card] | None = None,
) -> TributeFlowResult:
    """按上一局名次对新局手牌执行进贡/还贡，并返回本局先手。

    单下：末游向头游进贡；若末游自己有 2 大王则抗贡，头游先手。
    双下：三游和末游都进贡；若二者合计有 2 大王则抗贡，头游先手。
    双贡时大贡给头游、小贡给二游；同点数按顺时针，靠近头游左侧者进贡给头游。
    """
    if len(finish_order) < 3:
        return TributeFlowResult(
            first_player=finish_order[0] if finish_order else 0,
            resisted=False,
            exchanges=[],
            events=[],
        )

    destination_hands = hands
    hands = [list(hand) for hand in destination_hands]

    def commit(result: TributeFlowResult) -> TributeFlowResult:
        for destination, source in zip(destination_hands, hands):
            destination[:] = source
        return result

    head = finish_order[0]
    second = finish_order[1]
    third = finish_order[2]
    last = _last_player(finish_order)
    events: list[Event] = []
    tribute_choices = tribute_choices or {}
    return_choices = return_choices or {}

    def choose_tribute(player: int) -> Card:
        legal = legal_tribute_cards(hands[player], wild_card, level)
        if not legal:
            raise ValueError("no legal tribute card")
        chosen = tribute_choices.get(player)
        if chosen is None:
            return select_tribute_card(hands[player], wild_card, level)
        if chosen not in legal:
            raise ValueError(f"illegal tribute card selected by player {player}")
        return chosen

    def choose_return(player: int) -> Card:
        legal = legal_return_cards(hands[player], level)
        if not legal:
            raise ValueError("no legal return tribute card")
        chosen = return_choices.get(player)
        if chosen is None:
            return select_return_card(hands[player], level)
        if chosen not in legal:
            raise ValueError(f"illegal return tribute card selected by player {player}")
        return chosen

    if third % 2 != last % 2:
        if _tribute_team_has_two_big_jokers(hands, [last]):
            events.append(TributeResisted(player=last, team=last % 2, reason="single"))
            return TributeFlowResult(head, True, [], events)
        tribute_card = choose_tribute(last)
        hands[last].remove(tribute_card)
        hands[head].append(tribute_card)
        events.append(TributeSent(last, head, tribute_card, reason="single"))
        return_card = choose_return(head)
        hands[head].remove(return_card)
        hands[last].append(return_card)
        events.append(TributeReturned(head, last, return_card, reason="single"))
        exchange = TributeExchange(last, head, tribute_card, return_card)
        return commit(TributeFlowResult(last, False, [exchange], events))

    tribute_players = [third, last]
    if _tribute_team_has_two_big_jokers(hands, tribute_players):
        for player in tribute_players:
            events.append(
                TributeResisted(player=player, team=player % 2, reason="double")
            )
        return TributeFlowResult(head, True, [], events)

    tribute_cards = {player: choose_tribute(player) for player in tribute_players}
    comparison = compare_tribute_cards(
        tribute_cards[third],
        tribute_cards[last],
        level=level,
        same_rank_ties=True,
    )
    if comparison > 0:
        head_tributer = third
    elif comparison < 0:
        head_tributer = last
    else:
        # 同点数按顺时针进贡，头游顺时针方向先遇到的进贡给头游。
        cursor = _clockwise_next(head)
        while cursor not in tribute_players:
            cursor = _clockwise_next(cursor)
        head_tributer = cursor
    second_tributer = last if head_tributer == third else third

    assignments = [(head_tributer, head), (second_tributer, second)]
    exchanges: list[TributeExchange] = []
    for from_player, to_player in assignments:
        tribute_card = tribute_cards[from_player]
        hands[from_player].remove(tribute_card)
        hands[to_player].append(tribute_card)
        events.append(TributeSent(from_player, to_player, tribute_card, reason="double"))
        exchanges.append(TributeExchange(from_player, to_player, tribute_card))

    for exchange in exchanges:
        return_card = choose_return(exchange.to_player)
        hands[exchange.to_player].remove(return_card)
        hands[exchange.from_player].append(return_card)
        exchange.return_card = return_card
        events.append(
            TributeReturned(
                exchange.to_player,
                exchange.from_player,
                return_card,
                reason="double",
            )
        )

    return commit(TributeFlowResult(head_tributer, False, exchanges, events))


def resolve_tribute(
    upstream: int,
    downstream: int,
    upstream_hand: List[Card],
    downstream_hand: List[Card],
    *,
    level: int | None = None,
    wild_card: Card | None = None,
) -> TributeResult:
    """兼容旧接口：计算单次进 / 还贡结果，但不修改手牌。

    新局真实换牌请使用 `apply_tribute_flow()`；本函数保留给旧测试和旧调用。
    """
    if can_resist_tribute(downstream_hand):
        return TributeResult(
            resisted=True,
            tribute_card=None,
            return_card=None,
            first_player_after=upstream,
        )

    tribute = select_tribute_card(downstream_hand, wild_card, level)
    remaining_upstream = [*list(upstream_hand), tribute]

    return_card = select_return_card(remaining_upstream, level)

    # 进 / 还贡后：从进贡方起牌（downstream）
    return TributeResult(
        resisted=False,
        tribute_card=tribute,
        return_card=return_card,
        first_player_after=downstream,
    )

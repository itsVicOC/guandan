"""信息集确定化（Determinization）。

在不完全信息游戏中，玩家无法看到其他玩家的手牌。确定化是指：
根据已知信息（自己手牌、已出牌历史），生成一个"可能的世界"——
随机分配其他玩家的手牌，使得：
1. 每家手牌数与实际相符
2. 已出牌不会重复分配
3. 从未出牌池中随机抽取

MCTS 将在这个确定化的世界中进行搜索。
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import List

from ...engine.card import RANK_2, RANK_A, RANK_BIG_JOKER, RANK_SMALL_JOKER, Card, Suit
from ...engine.events import Pass, TributeReturned, TributeSent, TurnPlayed
from ...engine.hand import Pattern, PatternType, comparison_rank, effective_rank
from ...engine.state import GameState, is_teammate


@dataclass(frozen=True)
class PassEvidence:
    """Public evidence attached to a pass on a particular table top."""

    player: int
    top_player: int
    pattern: Pattern


def collect_pass_evidence(state: GameState) -> tuple[PassEvidence, ...]:
    """Extract contextual pass observations from the public event stream."""
    top_player: int | None = None
    top_pattern: Pattern | None = None
    evidence: list[PassEvidence] = []
    for event in state.history:
        if isinstance(event, TurnPlayed):
            top_player = event.player
            top_pattern = event.pattern
        elif isinstance(event, Pass) and top_player is not None and top_pattern is not None:
            evidence.append(PassEvidence(event.player, top_player, top_pattern))
    return tuple(evidence)


def card_owner_likelihood(
    card: Card,
    owner: int,
    evidence: tuple[PassEvidence, ...],
    *,
    level: int,
) -> float:
    """Return a soft likelihood for assigning ``card`` to ``owner``.

    Passing while an opponent controls the trick is evidence, not proof.  A
    player may deliberately hold back or let a teammate run, so likelihoods
    stay strictly positive and only singles receive a strong update.
    """
    likelihood = 1.0
    for observation in evidence:
        if observation.player != owner or is_teammate(owner, observation.top_player):
            continue
        top = observation.pattern
        card_rank = effective_rank(card.rank, level)
        top_rank = comparison_rank(top, level)
        if top.type == PatternType.SINGLE and card_rank > top_rank:
            likelihood *= 0.58
        elif top.type == PatternType.PAIR and card_rank > top_rank:
            likelihood *= 0.82
        elif top.type in (PatternType.TRIPLE, PatternType.TRIPLE_PAIR) and card_rank > top_rank:
            likelihood *= 0.90
    return max(0.05, likelihood)


def _weighted_owner(
    card: Card,
    capacities: dict[int, int],
    evidence: tuple[PassEvidence, ...],
    *,
    level: int,
    rng: random.Random,
) -> int:
    owners = [owner for owner, capacity in capacities.items() if capacity > 0]
    if not owners:
        raise ValueError("belief sampler has no remaining hand capacity")
    weights = [card_owner_likelihood(card, owner, evidence, level=level) for owner in owners]
    threshold = rng.random() * sum(weights)
    cumulative = 0.0
    for owner, weight in zip(owners, weights):
        cumulative += weight
        if threshold <= cumulative:
            return owner
    return owners[-1]


def _get_all_cards_in_game() -> List[Card]:
    """获取游戏中所有的牌（2副牌共108张）。"""
    cards: List[Card] = []

    # 普通牌：2-A，每种4张（2副×2张）
    for rank in range(RANK_2, RANK_A + 1):
        for suit in [Suit.SPADES, Suit.HEARTS, Suit.CLUBS, Suit.DIAMONDS]:
            cards.append(Card(rank, suit))
            cards.append(Card(rank, suit))  # 第二副

    # 王牌：各2张
    cards.extend([
        Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER),
        Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER),
        Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
        Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
    ])

    return cards


def determinize(state: GameState, player: int, rng: random.Random) -> GameState:
    """为其他3家分配可能的手牌（信息集确定化）。

    Args:
        state: 当前游戏状态
        player: 当前玩家（MCTS 搜索的根玩家）
        rng: 随机数生成器（测试时可 seed）

    Returns:
        新的 GameState，其他3家的手牌被重新随机分配

    约束：
    1. 每家手牌数 = state.hand_size(p)
    2. 已出牌不能再分配
    3. 自己的手牌保持不变
    4. 从未出牌池中随机抽取
    """
    # 1. 获取所有牌
    all_cards = _get_all_cards_in_game()

    # 2. 统计已出牌，并从完整牌池中逐张移除。
    played_cards_list: List[Card] = []
    known_hands: list[list[Card]] = [[], [], [], []]
    for ev in state.history:
        if isinstance(ev, TurnPlayed):
            played_cards_list.extend(ev.pattern.cards)
            for card in ev.pattern.cards:
                if card in known_hands[ev.player]:
                    known_hands[ev.player].remove(card)
        elif isinstance(ev, (TributeSent, TributeReturned)):
            if ev.card in known_hands[ev.from_player]:
                known_hands[ev.from_player].remove(ev.card)
            known_hands[ev.to_player].append(ev.card)

    unplayed_cards = all_cards.copy()
    for played_card in played_cards_list:
        if played_card in unplayed_cards:
            unplayed_cards.remove(played_card)

    # 4. 从未出牌池中移除当前玩家的手牌
    my_hand = state.hands[player]
    for card in my_hand:
        if card in unplayed_cards:
            unplayed_cards.remove(card)

    # Public tribute events reveal a card's exact owner until that card is played.
    # Reserve those cards before shuffling the rest of the hidden information set.
    for owner, cards in enumerate(known_hands):
        if owner == player:
            continue
        known_hands[owner] = cards[: state.hand_size(owner)]
        for card in known_hands[owner]:
            if card in unplayed_cards:
                unplayed_cards.remove(card)

    # 5. Shuffle first so equal-weight worlds remain uniformly varied, then
    # assign cards with contextual pass evidence as a soft likelihood.
    rng.shuffle(unplayed_cards)

    # 6. 创建新状态（深拷贝）
    new_state = copy.deepcopy(state)

    # 7. 为其他3家重新分配手牌。按 card 选择 owner，避免固定按座位切片
    # 带来的分配顺序偏差，同时严格满足每家的公开剩余张数。
    capacities = {
        p: state.hand_size(p) - len(known_hands[p])
        for p in range(4)
        if p != player
    }
    sampled = {p: list(known_hands[p]) for p in capacities}
    pass_evidence = collect_pass_evidence(state)
    for card in unplayed_cards:
        owner = _weighted_owner(
            card,
            capacities,
            pass_evidence,
            level=state.level,
            rng=rng,
        )
        sampled[owner].append(card)
        capacities[owner] -= 1

    for owner, cards in sampled.items():
        new_state.hands[owner] = cards

    return new_state

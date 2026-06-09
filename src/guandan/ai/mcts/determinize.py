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
from typing import List

from ...engine.card import RANK_2, RANK_A, RANK_BIG_JOKER, RANK_SMALL_JOKER, Card, Suit
from ...engine.state import GameState


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
    for ev in state.history:
        from ...engine.events import TurnPlayed
        if isinstance(ev, TurnPlayed):
            played_cards_list.extend(ev.pattern.cards)

    unplayed_cards = all_cards.copy()
    for played_card in played_cards_list:
        if played_card in unplayed_cards:
            unplayed_cards.remove(played_card)

    # 4. 从未出牌池中移除当前玩家的手牌
    my_hand = state.hands[player]
    for card in my_hand:
        if card in unplayed_cards:
            unplayed_cards.remove(card)

    # 5. 随机打乱未出牌池
    rng.shuffle(unplayed_cards)

    # 6. 创建新状态（深拷贝）
    new_state = copy.deepcopy(state)

    # 7. 为其他3家重新分配手牌
    idx = 0
    for p in [0, 1, 2, 3]:
        if p == player:
            # 自己的手牌保持不变
            continue

        hand_size = state.hand_size(p)
        new_state.hands[p] = unplayed_cards[idx : idx + hand_size]
        idx += hand_size

    return new_state

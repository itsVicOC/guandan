"""MCTS 主循环：Selection、Expansion、Simulation、Backpropagation。

标准 MCTS 四个阶段：
1. Selection: 从根节点用 UCB1 选择最优路径到叶子节点
2. Expansion: 扩展一个新子节点
3. Simulation: 从新节点快速玩到游戏结束（rollout）
4. Backpropagation: 将结果回传到路径上所有节点
"""
from __future__ import annotations

import copy
import math
from typing import Optional

from ...engine.card import Card
from ...engine.hand import Pattern, PatternType, comparison_rank
from ...engine.rules.patterns import find_complete_pattern
from ...engine.rules.scoring import compute_level_change
from ...engine.state import (
    GameState,
    IllegalPlayError,
    is_teammate,
    pass_turn,
    play_pattern,
)
from ...engine.trick import current_top_player
from ..valuation import enumerate_candidate_plays
from .node import MCTSNode


def ucb1_score(node: MCTSNode, parent_visits: int, c: float = 1.41) -> float:
    """计算 UCB1 分数。

    UCB1 = exploitation + exploration
         = win_rate + C * sqrt(ln(parent_visits) / node_visits)

    Args:
        node: 子节点
        parent_visits: 父节点的访问次数
        c: 探索常数（默认 sqrt(2) ≈ 1.41）

    Returns:
        UCB1 分数，越大越优先访问
    """
    if node.visits == 0:
        return float('inf')  # 未访问节点优先

    exploit = node.win_rate()
    explore = c * math.sqrt(math.log(parent_visits) / node.visits)
    return exploit + explore


def _select(node: MCTSNode, c: float) -> MCTSNode:
    """Selection: 用 UCB1 选择最优路径到叶子节点。

    从根节点出发，每次选择 UCB1 分数最高的子节点，
    直到：
    1. 到达未完全展开的节点，或
    2. 到达终局节点
    """
    while not node.is_terminal():
        if not node.is_fully_expanded():
            return node
        # 如果没有子节点，说明需要先展开
        if not node.children:
            return node
        # 选择 UCB1 最大的子节点
        node = max(node.children, key=lambda child: ucb1_score(child, node.visits, c))
    return node


def _get_legal_actions(
    state: GameState, player: int, max_actions: int = 5
) -> list[Optional[Pattern]]:
    """获取合法动作列表。

    Args:
        state: 当前状态
        player: 当前玩家
        max_actions: 最多返回几个候选（剪枝）

    Returns:
        合法动作列表（None 表示过牌）
    """
    actions: list[Optional[Pattern]] = []

    # 获取候选出牌
    candidates = enumerate_candidate_plays(state, player, max_candidates=max_actions)

    if candidates:
        actions.extend(candidates[:max_actions])

    # 如果不是 leader，可以过牌
    if state.table:
        actions.append(None)

    return actions


def _expand(node: MCTSNode, max_actions: int) -> MCTSNode:
    """Expansion: 从 untried_actions 中选一个，创建新子节点。

    Args:
        node: 待扩展的节点
        max_actions: 最多考虑几个候选动作

    Returns:
        新创建的子节点
    """
    if not node.untried_actions:
        # 首次展开，初始化 untried_actions
        node.untried_actions = _get_legal_actions(
            node.state, node.player, max_actions=max_actions
        )

    if not node.untried_actions:
        return node  # 无可用动作

    # 弹出一个未尝试的动作
    action = node.untried_actions.pop()

    # 应用动作，生成新状态
    new_state = copy.deepcopy(node.state)
    try:
        if action is None:
            pass_turn(new_state, node.player)
        else:
            play_pattern(new_state, node.player, action)
    except IllegalPlayError:
        # 动作非法（理论上不应该发生），跳过
        return node

    # 创建子节点
    child = MCTSNode(
        state=new_state,
        player=new_state.current_player(),
        parent=node,
        action=action,
    )

    node.children.append(child)
    return child


def _simulate(
    node: MCTSNode,
    root_player: int,
    rollout_strategy_level: int,
    max_turns: int,
) -> float:
    """Simulation: 从 node 开始快速玩到游戏结束（rollout）。

    使用快速策略（如档1）玩到结束，评估结果。

    Args:
        node: 起始节点
        root_player: 根玩家（用于评估结果）
        rollout_strategy_level: rollout 策略档位（默认1）
        max_turns: 单次 rollout 最多模拟多少手

    Returns:
        从 root_player 视角的胜率（0.0 - 1.0）
    """
    sim_state = copy.deepcopy(node.state)

    # 用 rollout 策略玩到结束
    turn_count = 0

    while not sim_state.finished and turn_count < max_turns:
        player = sim_state.current_player()
        pattern = _rollout_select_pattern(
            sim_state,
            player,
            rollout_strategy_level=rollout_strategy_level,
        )

        try:
            if pattern is None:
                pass_turn(sim_state, player)
            else:
                play_pattern(sim_state, player, pattern)
        except IllegalPlayError:
            # 策略返回非法动作，尝试过牌
            try:
                pass_turn(sim_state, player)
            except IllegalPlayError:
                # 无法过牌，游戏可能卡住，终止模拟
                break

        turn_count += 1

    # 评估结果
    return _evaluate_result(sim_state, root_player)


def _rollout_select_pattern(
    state: GameState,
    player: int,
    *,
    rollout_strategy_level: int,
) -> Optional[Pattern]:
    """MCTS rollout 的轻量出牌策略。

    Rollout 会在搜索中被调用很多次，这里使用最小合法牌型近似完整 AI 策略，
    避免每一步都运行昂贵的手牌结构估值。档 2+ 保留一个关键协作行为：
    队友正在桌顶时选择过牌。
    """
    if rollout_strategy_level >= 2 and state.table:
        top_player = current_top_player(state)
        if top_player is not None and is_teammate(top_player, player):
            return None
    return _smallest_rollout_pattern(state, player)


def _smallest_rollout_pattern(state: GameState, player: int) -> Optional[Pattern]:
    """rollout 专用快速候选：只枚举低成本基础牌型，必要时找炸弹。"""
    hand = state.hands[player]
    if not hand:
        return None
    if len(hand) <= 10:
        finish = find_complete_pattern(hand, state.wild_card)
        if finish is not None and (
            not state.table or finish.can_be_played_on(state.table[-1], level=state.level)
        ):
            return finish

    table_top = state.table[-1] if state.table else None
    if table_top is None:
        return _smallest_basic_pattern(hand, state.wild_card, state.level)

    same_type = [
        pattern
        for pattern in _basic_patterns(hand, state.wild_card)
        if pattern.type == table_top.type
        and pattern.length == table_top.length
        and pattern.can_be_played_on(table_top, level=state.level)
    ]
    if same_type:
        return min(same_type, key=lambda p: _rollout_pattern_key(p, state.level))

    bombs = [
        pattern
        for pattern in _fast_bomb_patterns(hand, state.wild_card)
        if pattern.can_be_played_on(table_top, level=state.level)
    ]
    if bombs:
        return min(bombs, key=lambda p: _rollout_pattern_key(p, state.level))
    return None


def _smallest_basic_pattern(
    hand: list[Card],
    wild_card: Optional[Card],
    level: int,
) -> Optional[Pattern]:
    basics = _basic_patterns(hand, wild_card)
    if basics:
        return min(basics, key=lambda p: _rollout_pattern_key(p, level))
    bombs = _fast_bomb_patterns(hand, wild_card)
    return min(bombs, key=lambda p: _rollout_pattern_key(p, level), default=None)


def _rollout_pattern_key(pattern: Pattern, level: int) -> tuple[int, int, int, int]:
    return (
        pattern.weight,
        pattern.length,
        comparison_rank(pattern, level),
        pattern.wild_used,
    )


def _basic_patterns(hand: list[Card], wild_card: Optional[Card]) -> list[Pattern]:
    """快速生成单张/对子/三张，供 rollout 近似使用。"""
    wild_cards = _wild_cards_in(hand, wild_card)
    wild_count = len(wild_cards)
    normal = [card for card in hand if wild_card is None or card != wild_card]
    by_rank: dict[int, list[Card]] = {}
    for card in normal:
        by_rank.setdefault(card.rank, []).append(card)

    patterns: list[Pattern] = [
        Pattern(type=PatternType.SINGLE, rank=card.rank, length=1, cards=(card,))
        for card in normal
    ]
    if wild_count >= 1 and wild_card is not None:
        patterns.append(
            Pattern(
                type=PatternType.SINGLE,
                rank=wild_card.rank,
                length=1,
                cards=(wild_cards[0],),
                wild_used=1,
            )
        )

    for rank, cards in by_rank.items():
        if len(cards) >= 2:
            patterns.append(
                Pattern(type=PatternType.PAIR, rank=rank, length=1, cards=tuple(cards[:2]))
            )
        if len(cards) >= 3 and not cards[0].is_joker:
            patterns.append(
                Pattern(type=PatternType.TRIPLE, rank=rank, length=1, cards=tuple(cards[:3]))
            )
        if wild_count >= 1 and wild_card is not None and not cards[0].is_joker:
            if len(cards) >= 1:
                patterns.append(
                    Pattern(
                        type=PatternType.PAIR,
                        rank=rank,
                        length=1,
                        cards=(cards[0], wild_cards[0]),
                        wild_used=1,
                    )
                )
            if len(cards) >= 2:
                patterns.append(
                    Pattern(
                        type=PatternType.TRIPLE,
                        rank=rank,
                        length=1,
                        cards=(cards[0], cards[1], wild_cards[0]),
                        wild_used=1,
                    )
                )
        if (
            wild_count >= 2
            and wild_card is not None
            and len(cards) >= 1
            and not cards[0].is_joker
        ):
            patterns.append(
                Pattern(
                    type=PatternType.TRIPLE,
                    rank=rank,
                    length=1,
                    cards=(cards[0], wild_cards[0], wild_cards[1]),
                    wild_used=2,
                )
            )

    if wild_count >= 2 and wild_card is not None:
        patterns.append(
            Pattern(
                type=PatternType.PAIR,
                rank=wild_card.rank,
                length=1,
                cards=(wild_cards[0], wild_cards[1]),
                wild_used=2,
            )
        )
    if wild_count >= 3 and wild_card is not None:
        patterns.append(
            Pattern(
                type=PatternType.TRIPLE,
                rank=wild_card.rank,
                length=1,
                cards=(wild_cards[0], wild_cards[1], wild_cards[2]),
                wild_used=3,
            )
        )
    return patterns


def _fast_bomb_patterns(hand: list[Card], wild_card: Optional[Card]) -> list[Pattern]:
    """快速生成普通炸弹和四王炸，供 rollout 兜底使用。"""
    wild_cards_available = _wild_cards_in(hand, wild_card)
    wild_count = len(wild_cards_available)
    normal = [card for card in hand if wild_card is None or card != wild_card]
    by_rank: dict[int, list[Card]] = {}
    for card in normal:
        if not card.is_joker:
            by_rank.setdefault(card.rank, []).append(card)
    patterns: list[Pattern] = []

    big_jokers = [card for card in normal if card.is_big_joker]
    small_jokers = [card for card in normal if card.is_small_joker]
    if len(big_jokers) >= 2 and len(small_jokers) >= 2:
        patterns.append(
            Pattern(
                type=PatternType.FOUR_JOKERS,
                rank=max(card.rank for card in [*big_jokers[:2], *small_jokers[:2]]),
                length=4,
                cards=tuple([*big_jokers[:2], *small_jokers[:2]]),
            )
        )

    for rank, same_rank in by_rank.items():
        for natural_count in range(min(len(same_rank), 10), 0, -1):
            needed_wild = max(0, 4 - natural_count)
            total = natural_count + needed_wild
            if total < 4 or total > 10 or needed_wild > wild_count:
                continue
            wild_cards = wild_cards_available[:needed_wild]
            patterns.append(
                Pattern(
                    type=PatternType.BOMB,
                    rank=rank,
                    length=total,
                    cards=tuple([*same_rank[:natural_count], *wild_cards]),
                    wild_used=needed_wild,
                )
            )
            break
    return patterns


def _wild_cards_in(hand: list[Card], wild_card: Optional[Card]) -> list[Card]:
    if wild_card is None:
        return []
    return [card for card in hand if card == wild_card]


def _evaluate_result(state: GameState, root_player: int) -> float:
    """评估终局结果（从 root_player 视角）。

    完整终局按升级收益评分；未完成 rollout 用已出完名次和剩余手牌做保守启发。

    Args:
        state: 终局状态
        root_player: 根玩家

    Returns:
        胜率（0.0 - 1.0）
    """
    if not state.finish_order:
        return _evaluate_unfinished(state, root_player)

    if state.finished:
        full_order = list(state.finish_order)
        full_order.extend(player for player in range(4) if player not in full_order)
        head, second, third, last = full_order[:4]
        deltas = compute_level_change(
            head, second, third, last, state.team_bomb_count
        )
        my_team = root_player % 2
        opponent_team = 1 - my_team
        score = 0.5 + (deltas[my_team] - deltas[opponent_team]) / 6.0
        if is_teammate(head, root_player):
            score += 0.10
        else:
            score -= 0.10
        return max(0.0, min(1.0, score))

    return _evaluate_unfinished(state, root_player)


def _evaluate_unfinished(state: GameState, root_player: int) -> float:
    """rollout 未完成时的启发式局面分。"""
    score = 0.5
    for rank, player in enumerate(state.finish_order, start=1):
        if is_teammate(player, root_player):
            score += {1: 0.22, 2: 0.12, 3: 0.05}.get(rank, 0.0)
        else:
            score -= {1: 0.22, 2: 0.12, 3: 0.05}.get(rank, 0.0)

    my_cards = sum(
        state.hand_size(player)
        for player in range(4)
        if is_teammate(player, root_player) and player not in state.finish_order
    )
    opponent_cards = sum(
        state.hand_size(player)
        for player in range(4)
        if not is_teammate(player, root_player) and player not in state.finish_order
    )
    if my_cards + opponent_cards:
        score += (opponent_cards - my_cards) / (my_cards + opponent_cards) * 0.15

    return max(0.0, min(1.0, score))


def _backpropagate(node: MCTSNode, result: float) -> None:
    """Backpropagation: 将结果回传到路径上所有节点。

    Args:
        node: 起始节点
        result: 模拟结果（0.0 - 1.0）
    """
    current: Optional[MCTSNode] = node
    while current is not None:
        current.visits += 1
        current.wins += result
        current = current.parent


def mcts_search(
    root: MCTSNode,
    iterations: int = 200,
    ucb_c: float = 1.41,
    max_actions: int = 5,
    rollout_strategy: int = 1,
    rollout_max_turns: int = 80,
) -> Optional[MCTSNode]:
    """MCTS 主循环。

    Args:
        root: 根节点
        iterations: 迭代次数
        ucb_c: UCB1 探索常数
        max_actions: 每个节点考虑的最大候选动作数
        rollout_strategy: rollout 策略档位
        rollout_max_turns: 单次 rollout 最多模拟多少手

    Returns:
        最佳子节点（访问次数最多）
    """
    root_player = root.player

    for _ in range(iterations):
        # 1. Selection
        node = _select(root, ucb_c)

        # 2. Expansion
        if not node.is_terminal():
            node = _expand(node, max_actions)

        # 3. Simulation
        result = _simulate(node, root_player, rollout_strategy, rollout_max_turns)

        # 4. Backpropagation
        _backpropagate(node, result)

    # 返回访问次数最多的子节点
    if not root.children:
        return None

    return max(root.children, key=lambda c: c.visits)

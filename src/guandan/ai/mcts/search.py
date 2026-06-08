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

from ...engine.hand import Pattern
from ...engine.state import (
    GameState,
    IllegalPlayError,
    is_teammate,
    pass_turn,
    play_pattern,
)
from ..strategy import make_strategy
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


def _simulate(node: MCTSNode, root_player: int, rollout_strategy_level: int) -> float:
    """Simulation: 从 node 开始快速玩到游戏结束（rollout）。

    使用快速策略（如档1）玩到结束，评估结果。

    Args:
        node: 起始节点
        root_player: 根玩家（用于评估结果）
        rollout_strategy_level: rollout 策略档位（默认1）

    Returns:
        从 root_player 视角的胜率（0.0 - 1.0）
    """
    sim_state = copy.deepcopy(node.state)

    # 创建 rollout 策略
    rollout_strategy = make_strategy(rollout_strategy_level)

    # 用 rollout 策略玩到结束
    max_turns = 200  # 防止死循环
    turn_count = 0

    while not sim_state.finished and turn_count < max_turns:
        player = sim_state.current_player()
        pattern = rollout_strategy.select_pattern(sim_state, player)

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


def _evaluate_result(state: GameState, root_player: int) -> float:
    """评估终局结果（从 root_player 视角）。

    返回值：
    - 1.0: 队友头游
    - 0.0: 对方头游
    - 0.5: 未完成（超时）

    Args:
        state: 终局状态
        root_player: 根玩家

    Returns:
        胜率（0.0 - 1.0）
    """
    if not state.finish_order:
        return 0.5  # 未完成，返回中性值

    first_player = state.finish_order[0]

    if is_teammate(first_player, root_player):
        # 我方头游
        return 1.0
    else:
        # 对方头游
        return 0.0


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
) -> Optional[MCTSNode]:
    """MCTS 主循环。

    Args:
        root: 根节点
        iterations: 迭代次数
        ucb_c: UCB1 探索常数
        max_actions: 每个节点考虑的最大候选动作数
        rollout_strategy: rollout 策略档位

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
        result = _simulate(node, root_player, rollout_strategy)

        # 4. Backpropagation
        _backpropagate(node, result)

    # 返回访问次数最多的子节点
    if not root.children:
        return None

    return max(root.children, key=lambda c: c.visits)

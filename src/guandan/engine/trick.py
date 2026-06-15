"""当前牌墩辅助函数。

这些函数只依赖 engine 事件流和 GameState 的公开字段，用来统一状态机、AI
和 TUI 对"当前 trick/桌顶玩家/已锁定过牌玩家"的理解。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Union

from .events import Pass, TurnPlayed
from .hand import Pattern

if TYPE_CHECKING:
    from .state import GameState

TrickAction = Union[TurnPlayed, Pass]


def current_trick_actions(state: GameState) -> List[TrickAction]:
    """从事件历史尾部提取当前 trick 的出牌/过牌事件。

    `state.table` 是当前牌墩尚未收走的出牌列表。本函数从历史尾部向前对齐
    table，避免把上一个牌墩中同一玩家的过牌误认为当前牌墩的锁定过牌。
    """
    if not state.table:
        return []

    table_idx = len(state.table) - 1
    actions_reversed: List[TrickAction] = []
    for ev in reversed(state.history):
        if isinstance(ev, Pass):
            if ev.player in state.passed_players:
                actions_reversed.append(ev)
            continue
        if isinstance(ev, TurnPlayed) and table_idx >= 0 and ev.pattern == state.table[table_idx]:
            actions_reversed.append(ev)
            table_idx -= 1
            if table_idx < 0:
                break
    return list(reversed(actions_reversed))


def last_player_of_pattern(
    state: GameState,
    pattern: Pattern,
    *,
    default: Optional[int] = None,
) -> Optional[int]:
    """返回当前 trick 中某手牌的最后出牌者；历史不完整时回退到全历史查找。"""
    for trick_ev in reversed(current_trick_actions(state)):
        if isinstance(trick_ev, TurnPlayed) and trick_ev.pattern == pattern:
            return trick_ev.player
    for history_ev in reversed(state.history):
        if isinstance(history_ev, TurnPlayed) and history_ev.pattern == pattern:
            return history_ev.player
    return default


def current_table_players(state: GameState) -> List[int]:
    """返回当前桌面每手牌对应的玩家，顺序与 `state.table` 一致。"""
    players = [
        ev.player for ev in current_trick_actions(state) if isinstance(ev, TurnPlayed)
    ]
    if len(players) == len(state.table):
        return players
    return [
        player
        for player in (
            last_player_of_pattern(state, pattern, default=state.leader)
            for pattern in state.table
        )
        if player is not None
    ]


def current_top_player(state: GameState) -> Optional[int]:
    """当前桌面最大牌所属玩家；table 为空时返回本轮先手。"""
    if not state.table:
        return state.leader
    players = current_table_players(state)
    if players:
        return players[-1]
    return state.leader


def locked_passed_players(state: GameState) -> List[int]:
    """提取本轮仍被锁定的过牌玩家，按过牌发生顺序。"""
    passed: List[int] = []
    for ev in current_trick_actions(state):
        if isinstance(ev, Pass) and ev.player in state.passed_players and ev.player not in passed:
            passed.append(ev.player)
    for player in range(4):
        if player in state.passed_players and player not in passed:
            passed.append(player)
    return passed

"""升级 / 过 A 规则。

简化版：每局按上游+次游与中游+末游的级数差升级。
- 双上：+3
- 双下：-3
- 一般：每上游 +1，末游 -1
- 炸弹数翻倍：本局某队出的炸弹数累加
"""
from __future__ import annotations

from typing import List, Tuple


def compute_level_change(
    finish_order: List[int], team_bomb_count: List[int]
) -> Tuple[int, int]:
    """计算两队的级数变化。

    Args:
        finish_order: 已出完牌的玩家顺序（[上游, 次游, ...]）
        team_bomb_count: [team0_bomb_count, team1_bomb_count]

    Returns:
        (delta_team0, delta_team1)
    """
    if len(finish_order) < 2:
        # 一局还没结束
        return (0, 0)

    upstream = finish_order[0]
    second = finish_order[1]
    upstream_team = upstream % 2
    second_team = second % 2

    delta = [0, 0]

    if upstream_team == second_team:
        # 双上：+3
        delta[upstream_team] = 3
        # 双下：另一队 -3
        other = 1 - upstream_team
        delta[other] = -3
    else:
        # 单上：上游队 +1
        delta[upstream_team] = 1
        # 末游：另一队 -1
        other = 1 - upstream_team
        delta[other] = -1

    # 炸弹数翻倍：每多 1 个炸弹 +1
    for team in (0, 1):
        delta[team] += team_bomb_count[team]

    return (delta[0], delta[1])

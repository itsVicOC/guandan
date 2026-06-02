"""升级 / 过 A 规则。

按文档《掼蛋的接风判定与四名次的产生规则》：

升级规则（仅头游方升级，对方不降级）：
- 头游 + 二游（己方包揽前 2 名）= 升 3 级
- 头游 + 三游（己方头游 + 队友三游）= 升 2 级
- 头游 + 末游（己方头游 + 队友末游）= 升 1 级

加炸弹翻倍：上游方每多 1 个炸弹，额外 +1。

过 A（在 A 这一局）：
- 必须"双上"（头游 + 队友非末游，即头游+二游 或 头游+三游）→ 过 A 成功
- 若头游+末游 → 冲 A 失败

注意：升级只在头游方。对方不降级。
"""
from __future__ import annotations

from typing import List, Tuple


def compute_level_change(
    head: int,
    second: int,
    third: int,
    last: int,
    team_bomb_count: List[int],
) -> Tuple[int, int]:
    """计算两队的级数变化（delta）。

    Args:
        head: 头游玩家索引
        second: 二游玩家索引
        third: 三游玩家索引
        last: 末游玩家索引
        team_bomb_count: [team0_bomb_count, team1_bomb_count]

    Returns:
        (delta_team0, delta_team1) 头游方升级 1/2/3 级，对方不升级
    """
    # 头游所在队
    head_team = head % 2
    other_team = 1 - head_team
    # 头游队友（对家）的名次
    partner = (head + 2) % 4
    if partner == second:
        partner_rank = 2
    elif partner == third:
        partner_rank = 3
    else:
        partner_rank = 4  # 末游

    # 基础升级数
    base = {2: 3, 3: 2, 4: 1}.get(partner_rank, 0)

    # 加上本局上游方出的炸弹数
    delta_head = base + team_bomb_count[head_team]
    # 对方不降级
    delta_other = 0

    if head_team == 0:
        return (delta_head, delta_other)
    else:
        return (delta_other, delta_head)

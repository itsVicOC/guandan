"""升级 / 过 A 规则。

按文档《掼蛋的接风判定与四名次的产生规则》：

升级规则（仅头游方升级，对方不降级）：
- 头游 + 二游（己方包揽前 2 名）= 升 3 级
- 头游 + 三游（己方头游 + 队友三游）= 升 2 级
- 头游 + 末游（己方头游 + 队友末游）= 升 1 级

额外奖励：
- 漂牌（上游最后一手为 5 张+级牌炸弹）→ 头游方再 +3 级

注意：升级只在头游方。对方不降级。**炸弹不翻倍**。
"""
from __future__ import annotations

from typing import List, Tuple


def compute_level_change(
    head: int,
    second: int,
    third: int,
    last: int,
    team_bomb_count: List[int] = None,
) -> Tuple[int, int]:
    """计算两队的级数变化（delta）。

    Args:
        head: 头游玩家索引
        second: 二游玩家索引
        third: 三游玩家索引
        last: 末游玩家索引
        team_bomb_count: 保留参数以兼容旧调用，但**不参与升级计算**

    Returns:
        (delta_team0, delta_team1) 头游方升级 1/2/3 级，对方不升级
    """
    # 头游所在队
    head_team = head % 2
    # 头游队友（对家）的名次
    partner = (head + 2) % 4
    if partner == second:
        partner_rank = 2
    elif partner == third:
        partner_rank = 3
    else:
        partner_rank = 4  # 末游

    # 基础升级数（仅按名次组合，不含炸弹）
    base = {2: 3, 3: 2, 4: 1}.get(partner_rank, 0)

    delta_head = base
    # 对方不降级
    delta_other = 0

    if head_team == 0:
        return (delta_head, delta_other)
    else:
        return (delta_other, delta_head)


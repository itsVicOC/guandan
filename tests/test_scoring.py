"""升级 / 过 A 测试（按文档规则）。"""
from __future__ import annotations

from guandan.engine.rules.scoring import compute_level_change


class TestComputeLevelChange:
    def test_head_with_second_double_bonus(self):
        # 头游=0(队0), 二游=2(队0) → 头游+二游 → +3
        d0, d1 = compute_level_change(head=0, second=2, third=1, last=3, team_bomb_count=[0, 0])
        assert d0 == 3
        assert d1 == 0

    def test_head_with_third(self):
        # 头游=0(队0), 三游=2(队0), 队友是三游 → +2
        d0, d1 = compute_level_change(head=0, second=1, third=2, last=3, team_bomb_count=[0, 0])
        assert d0 == 2
        assert d1 == 0

    def test_head_with_last(self):
        # 头游=0(队0), 末游=2(队0), 队友是末游 → +1
        d0, d1 = compute_level_change(head=0, second=1, third=3, last=2, team_bomb_count=[0, 0])
        assert d0 == 1
        assert d1 == 0

    def test_head_with_partner_being_second_team1(self):
        # 头游=1(队1), 二游=3(队1) → 头游+二游 → +3 for team 1
        d0, d1 = compute_level_change(head=1, second=3, third=0, last=2, team_bomb_count=[0, 0])
        assert d0 == 0
        assert d1 == 3

    def test_bomb_does_not_bonus(self):
        """按文档：炸弹不影响升级，只按名次组合升级。"""
        # 即使出了 2 个炸弹，也只升 +3（头游+二游同队）
        d0, d1 = compute_level_change(head=0, second=2, third=1, last=3, team_bomb_count=[2, 0])
        assert d0 == 3
        assert d1 == 0

    def test_no_level_change_for_loser(self):
        """输方永远不降级（无论名次）。"""
        # 头游=0(队0), 二游=1(队1), 三游=2(队0=头游队友), 末游=3(队1)
        # 头游队友是三游 → +2
        d0, d1 = compute_level_change(head=0, second=1, third=2, last=3, team_bomb_count=[0, 0])
        assert d0 == 2
        assert d1 == 0  # 输方不降级

        # 头游=0, 队友(2)是末游
        d0, d1 = compute_level_change(head=0, second=1, third=3, last=2, team_bomb_count=[0, 0])
        assert d0 == 1
        assert d1 == 0  # 输方不降级

"""升级 / 过 A 测试。"""
from __future__ import annotations

from guandan.engine.rules.scoring import compute_level_change


class TestComputeLevelChange:
    def test_double_upgrade(self):
        # 上游、次游同队（0 和 2 都是队 0）→ 双上 +3
        delta0, delta1 = compute_level_change([0, 2], [0, 0])
        assert delta0 == 3
        assert delta1 == -3

    def test_single_upgrade(self):
        # 上游 0 (队 0), 次游 1 (队 1) → 单上 +1，单下 -1
        delta0, delta1 = compute_level_change([0, 1], [0, 0])
        assert delta0 == 1
        assert delta1 == -1

    def test_bomb_multiplier(self):
        # 上游队出了 2 个炸弹 → +1 + 2 = +3
        delta0, delta1 = compute_level_change([0, 1], [2, 0])
        assert delta0 == 3
        assert delta1 == -1

    def test_team1_wins(self):
        # 上游 1 (队 1), 次游 0 (队 0) → 队 1 +1, 队 0 -1
        delta0, delta1 = compute_level_change([1, 0], [0, 0])
        assert delta0 == -1
        assert delta1 == 1

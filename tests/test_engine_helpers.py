"""engine 新公开 API 单元测试。"""
from __future__ import annotations

from guandan.engine.state import (
    is_teammate,
    next_seat_counterclockwise,
    partner_of,
    team_of,
)


def test_next_seat_counterclockwise() -> None:
    # 逆时针出牌：东 -> 北 -> 西 -> 南 -> 东
    assert next_seat_counterclockwise(0) == 3
    assert next_seat_counterclockwise(3) == 2
    assert next_seat_counterclockwise(2) == 1
    assert next_seat_counterclockwise(1) == 0


def test_partner_of_seating_convention() -> None:
    # 东(0) 对 西(2)；南(1) 对 北(3)
    assert partner_of(0) == 2
    assert partner_of(1) == 3
    assert partner_of(2) == 0
    assert partner_of(3) == 1


def test_partner_is_involutive() -> None:
    # partner(partner(p)) == p
    for p in range(4):
        assert partner_of(partner_of(p)) == p


def test_is_teammate_true() -> None:
    # 东-西同队，南-北同队
    assert is_teammate(0, 2) is True
    assert is_teammate(2, 0) is True
    assert is_teammate(1, 3) is True
    assert is_teammate(3, 1) is True
    # 自反
    for p in range(4):
        assert is_teammate(p, p) is True


def test_is_teammate_false() -> None:
    # 跨队
    assert is_teammate(0, 1) is False
    assert is_teammate(0, 3) is False
    assert is_teammate(1, 2) is False
    assert is_teammate(2, 3) is False


def test_partner_of_is_teammate() -> None:
    # partner 一定是 teammate
    for p in range(4):
        assert is_teammate(p, partner_of(p))


def test_team_of_consistency() -> None:
    # team_of 跟 is_teammate 一致
    for a in range(4):
        for b in range(4):
            assert is_teammate(a, b) == (team_of(a) == team_of(b))

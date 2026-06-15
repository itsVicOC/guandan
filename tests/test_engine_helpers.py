"""engine 新公开 API 单元测试。"""
from __future__ import annotations

from guandan.engine.card import Card, Suit
from guandan.engine.events import Pass, TurnPlayed
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.state import (
    GameState,
    is_teammate,
    next_seat_counterclockwise,
    partner_of,
    team_of,
)
from guandan.engine.trick import (
    current_table_players,
    current_top_player,
    current_trick_actions,
    locked_passed_players,
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


def _single(rank: int, suit: Suit = Suit.HEARTS) -> Pattern:
    card = Card(rank, suit)
    return Pattern(PatternType.SINGLE, rank, 1, (card,), 0)


def test_current_trick_actions_ignore_old_passes() -> None:
    first = _single(4)
    press = _single(7)
    state = GameState(
        level=2,
        wild_card=None,
        hands=[[], [], [], []],
        turn_index=0,
        table=[first, press],
        passed_players={2, 3},
        leader=0,
        history=[
            Pass(player=2, hand_remaining=3),
            Pass(player=3, hand_remaining=3),
            TurnPlayed(player=0, pattern=first, hand_remaining=1),
            Pass(player=3, hand_remaining=1),
            Pass(player=2, hand_remaining=1),
            TurnPlayed(player=1, pattern=press, hand_remaining=0),
        ],
    )

    actions = current_trick_actions(state)

    assert actions == state.history[2:]
    assert current_table_players(state) == [0, 1]
    assert current_top_player(state) == 1
    assert locked_passed_players(state) == [3, 2]


def test_current_top_player_returns_leader_when_table_empty() -> None:
    state = GameState(
        level=2,
        wild_card=None,
        hands=[[], [], [], []],
        turn_index=2,
        leader=2,
    )

    assert current_trick_actions(state) == []
    assert current_table_players(state) == []
    assert current_top_player(state) == 2

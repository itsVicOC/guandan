"""GameState 集成测试。"""
from __future__ import annotations

import pytest

from guandan.engine.card import (
    RANK_5,
    RANK_6,
    RANK_7,
    RANK_8,
    RANK_A,
    RANK_K,
    Card,
    Suit,
)
from guandan.engine.events import Pass, TurnPlayed
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.state import (
    IllegalPlayError,
    make_initial_state,
    pass_turn,
    play_pattern,
)


def c(rank, suit="H"):
    s_map = {"H": Suit.HEARTS, "D": Suit.DIAMONDS, "S": Suit.SPADES, "C": Suit.CLUBS}
    return Card(rank, s_map[suit])


def single_pattern(card):
    return Pattern(PatternType.SINGLE, card.rank, 1, (card,), 0)


class TestInitialState:
    def test_initial_state(self):
        state = make_initial_state(level=2, first_player=0, seed=42)
        assert state.level == 2
        assert len(state.hands) == 4
        for h in state.hands:
            assert len(h) == 27
        assert state.turn_index == 0
        assert state.leader == 0
        assert not state.finished
        assert len(state.history) == 1  # ShuffleDeal
        assert state.wild_card is not None  # 打 2 时有红心 2

    def test_seed_reproducibility(self):
        s1 = make_initial_state(level=5, first_player=0, seed=42)
        s2 = make_initial_state(level=5, first_player=0, seed=42)
        for h1, h2 in zip(s1.hands, s2.hands):
            assert h1 == h2


class TestPlayPattern:
    def test_first_play(self):
        state = make_initial_state(level=2, first_player=0, seed=42)
        p = single_pattern(state.hands[0][0])
        play_pattern(state, 0, p)
        assert state.table == [p]
        assert state.hand_size(0) == 26
        assert state.turn_index == 1

    def test_press(self):
        state = make_initial_state(level=2, first_player=0, seed=42)
        c1 = state.hands[0][0]
        c2 = state.hands[1][0]
        # 让 player 0 出小，player 1 出大
        small, large = sorted([c1, c2], key=lambda c: c.rank)[:2]
        if c1.rank < c2.rank:
            p1 = single_pattern(c1)
            p2 = single_pattern(c2)
        else:
            p1 = single_pattern(c2)
            p2 = single_pattern(c1)
        play_pattern(state, 0, p1)
        play_pattern(state, 1, p2)
        assert state.table[-1] == p2
        assert state.turn_index == 2

    def test_cannot_press_smaller(self):
        state = make_initial_state(level=2, first_player=0, seed=42)
        # 找到 player 0 和 player 1 都有的一张牌
        p0_hand = state.hands[0]
        p1_hand = state.hands[1]
        # 假设 player 0 出大牌，player 1 想出小牌
        c_big = max(p0_hand, key=lambda c: (c.rank, c.is_joker))
        # 找一个 player 1 的小牌
        c_small = min(p1_hand, key=lambda c: (c.rank, not c.is_joker))
        p_big = single_pattern(c_big)
        p_small = single_pattern(c_small)
        play_pattern(state, 0, p_big)
        with pytest.raises(IllegalPlayError):
            play_pattern(state, 1, p_small)

    def test_cannot_play_out_of_turn(self):
        state = make_initial_state(level=2, first_player=0, seed=42)
        c = state.hands[2][0]
        p = single_pattern(c)
        with pytest.raises(IllegalPlayError):
            play_pattern(state, 2, p)


class TestPassTurn:
    def test_leader_cannot_pass(self):
        state = make_initial_state(level=2, first_player=0, seed=42)
        with pytest.raises(IllegalPlayError):
            pass_turn(state, 0)

    def test_pass_ends_trick_after_3(self):
        state = make_initial_state(level=2, first_player=0, seed=42)
        c = state.hands[0][0]
        play_pattern(state, 0, single_pattern(c))
        # 1, 2, 3 都过
        pass_turn(state, 1)
        pass_turn(state, 2)
        pass_turn(state, 3)
        # 第 3 次 pass 后，trick 应结束
        assert state.table == []
        assert state.turn_index == 0  # leader 重新开始
        assert state.trick_number == 1


class TestGameCompletion:
    def test_one_player_finishes(self):
        """模拟一个玩家出完所有牌。"""
        state = make_initial_state(level=2, first_player=0, seed=42)
        # 让 player 0 把所有 27 张牌都按单张出；其他玩家始终过牌
        all_cards = list(state.hands[0])
        # 排序：从小到大，最后几张出完时容易清空
        for c in all_cards:
            if state.finished:
                break
            # 如果不是 player 0 的回合，其他玩家过牌
            while state.turn_index != 0 and not state.finished:
                pass_turn(state, state.turn_index)
            p = single_pattern(c)
            play_pattern(state, 0, p)

        assert 0 in state.finish_order
        assert state.finished

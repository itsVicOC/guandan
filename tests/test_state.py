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
    def test_one_player_finishes_triggers_jiefeng(self):
        """1st player 完成后不停局，对家接风成为下一轮先手。"""
        state = make_initial_state(level=2, first_player=0, seed=42)
        # 让 player 0 把所有 27 张牌都按单张出
        all_cards = list(state.hands[0])
        for c in all_cards:
            if state.finished:
                break
            while state.turn_index != 0 and not state.finished:
                pass_turn(state, state.turn_index)
            p = single_pattern(c)
            play_pattern(state, 0, p)

        # 0 应该已经完成
        assert 0 in state.finish_order
        # 但游戏还没结束（要等 2nd finish）
        assert not state.finished
        # 对家 (2) 应成为下一轮先手
        assert state.turn_index == 2
        assert state.leader == 2
        assert state.table == []

    def test_two_players_finish_ends_game(self):
        """2nd player 完成后游戏才结束。"""
        state = make_initial_state(level=2, first_player=0, seed=42)
        # 让 player 0 先出完
        all_cards_0 = list(state.hands[0])
        for c in all_cards_0:
            if state.finished:
                break
            while state.turn_index != 0 and not state.finished:
                pass_turn(state, state.turn_index)
            p = single_pattern(c)
            play_pattern(state, 0, p)

        assert 0 in state.finish_order
        assert not state.finished  # 还没结束

        # 现在让 player 2（对家接风后是 leader）出完
        # 实际场景：player 2 是新 leader, 玩家 2 一直出到出完
        all_cards_2 = list(state.hands[2])
        for c in all_cards_2:
            if state.finished:
                break
            while state.turn_index != 2 and not state.finished:
                pass_turn(state, state.turn_index)
            p = single_pattern(c)
            play_pattern(state, 2, p)

        # 现在 game over
        assert state.finished
        # finish_order 头两个是 0 和 2
        assert state.finish_order[0] == 0
        assert state.finish_order[1] == 2
        # 同队 → 双上
        if hasattr(state, "team_levels_final"):
            assert state.team_levels_final[0] >= 3  # 至少 +3

    def test_third_fourth_by_hand_count(self):
        """三游/末游按手牌数：少者=三游，多者=末游。"""
        # 简化测试：手动构造状态
        from guandan.engine.card import Card, Suit
        from guandan.engine.hand import Pattern, PatternType
        from guandan.engine.events import ShuffleDeal, TurnPlayed

        # 构造一个状态：player 0 已完成, player 1 即将完成
        state = make_initial_state(level=2, first_player=0, seed=42)

        # 让 player 0 立即完成（出 1 张牌）
        # 但 state 已经有 27 张在 player 0 手牌里
        # 简化：直接修改 finish_order 然后 finish
        # 这里我们调用 _finish_game
        state.finish_order = [0, 1]  # 上游 0, 二游 1
        # 给剩余 player 2 一些牌，player 3 更多牌
        state.hands = [
            [],  # 0 finished
            [],  # 1 finished
            [Card(RANK_5, Suit.HEARTS)],  # 2 少
            [Card(RANK_5, Suit.HEARTS), Card(RANK_5, Suit.DIAMONDS)],  # 3 多
        ]
        # 调用内部 _finish_game
        from guandan.engine.state import _finish_game

        _finish_game(state)

        assert state.finished
        assert state.finish_order == [0, 1]
        # 三游 = 2 (少), 末游 = 3 (多)
        # 在 history 的 GameOver 事件里
        from guandan.engine.events import GameOver

        last = state.history[-1]
        assert isinstance(last, GameOver)
        assert last.finish_order == (0, 1, 2, 3)

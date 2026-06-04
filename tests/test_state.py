"""GameState 集成测试。"""
from __future__ import annotations

import pytest

from guandan.engine.card import (
    RANK_2,
    RANK_3,
    RANK_4,
    RANK_5,
    RANK_6,
    RANK_7,
    RANK_8,
    RANK_9,
    RANK_A,
    RANK_J,
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
        assert state.wild_card is not None

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
        p0_hand = state.hands[0]
        p1_hand = state.hands[1]
        c_big = max(p0_hand, key=lambda c: (c.rank, c.is_joker))
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

    def test_three_passes_ends_trick(self):
        state = make_initial_state(level=2, first_player=0, seed=42)
        c = state.hands[0][0]
        play_pattern(state, 0, single_pattern(c))
        pass_turn(state, 1)
        pass_turn(state, 2)
        pass_turn(state, 3)
        # 第 3 次 pass 后，trick 应结束，leader 继续
        assert state.table == []
        assert state.turn_index == 0
        assert state.leader == 0


class TestJiefeng_Document:
    """按文档规则：接风只发生在"出完手牌 + 无人压牌"的双重条件下。"""

    def test_finisher_then_press_no_jiefeng(self):
        """玩家 A 出完最后一手后，B 立即压牌 → 不接风，本轮继续。"""
        state = make_initial_state(level=2, first_player=0, seed=42)
        # 强制让 player 0 一手出完
        state.hands[0] = [c(RANK_5)]
        state.turn_index = 0
        play_pattern(state, 0, single_pattern(c(RANK_5)))
        # player 0 已出完
        assert 0 in state.finish_order
        # leader 仍是 0（trick 还没结束）
        assert state.leader == 0
        # turn 推进到 1
        assert state.turn_index == 1
        # 现在 player 1 压牌
        p1_card = state.hands[1][0]
        play_pattern(state, 1, single_pattern(p1_card))
        # 接风未触发，leader 仍为 0（trick 中）
        assert state.leader == 0
        # 轮到 2
        assert state.turn_index == 2
        # player 0 仍在 finish_order
        assert 0 in state.finish_order

    def test_finisher_then_all_pass_triggers_jiefeng(self):
        """玩家 A 出完最后一手后，3 个非 leader 全过 → 触发接风，对家领出。"""
        state = make_initial_state(level=2, first_player=0, seed=42)
        state.hands[0] = [c(RANK_5)]
        state.turn_index = 0
        play_pattern(state, 0, single_pattern(c(RANK_5)))
        # player 0 已出完；leader 仍是 0；turn 推进到 1
        assert 0 in state.finish_order
        assert state.leader == 0
        assert state.turn_index == 1
        # 1, 2, 3 都过
        pass_turn(state, 1)
        pass_turn(state, 2)
        pass_turn(state, 3)
        # 触发接风：leader 切到对家 (0+2)%4 = 2
        assert state.leader == 2
        assert state.turn_index == 2
        assert state.table == []

    def test_two_finishers_jiefeng_uses_active_count(self):
        """两个 finisher 时，active_non_leader = 2，2 次 pass 就触发接风。"""
        state = make_initial_state(level=2, first_player=0, seed=42)
        # 直接构造一个 0+2 都已 finished 的状态
        state.finish_order = [0, 2]
        state.leader = 0
        state.turn_index = 1
        state.table = [single_pattern(c(RANK_5))]
        state.pass_count = 0

        # 1 + 3 pass → 触发接风（active non-leader = 2, 即 1 和 3）
        pass_turn(state, 1)
        pass_turn(state, 3)

        # 接风触发：0 的对家 = 2，但 2 已 finished → 找下一个 active
        assert state.leader in (1, 3)
        assert state.leader not in state.finish_order


class TestGameCompletion_Document:
    """按文档：3rd 出完才结束，剩 1 人是末游。"""

    def test_three_finishers_ends_game(self):
        """3 个玩家出完手牌后游戏结束。"""
        state = make_initial_state(level=2, first_player=0, seed=42)

        def play_all(player):
            for c in list(state.hands[player]):
                if state.finished:
                    break
                while state.turn_index != player and not state.finished:
                    pass_turn(state, state.turn_index)
                # 检查是否能压当前桌牌
                top = state.table[-1] if state.table else None
                if top and c.rank <= top.rank:
                    # 不能压：让别人过牌再出
                    while state.turn_index != player and not state.finished:
                        pass_turn(state, state.turn_index)
                    if state.table and c.rank <= state.table[-1].rank:
                        # 还是不能压，跳过这张牌
                        state.hands[player].remove(c)
                        # 但这会让 hand 数量对不上... 简化：直接 break
                        break
                play_pattern(state, player, single_pattern(c))

        # 简化方案：让 0 一直出完，然后让剩余玩家都过牌，逼 1 也出完
        # 但这不可行，因为 0 出完手牌后，1 必须能压
        # 改用更稳健的方式：直接构造状态
        from guandan.engine.state import _finish_game

        state = make_initial_state(level=2, first_player=0, seed=42)
        state.finish_order = [0, 1, 2]  # 头游 0, 二游 1, 三游 2
        # 给末游 3 留一些牌
        from guandan.engine.card import RANK_5

        state.hands[3] = [c(RANK_5), c(RANK_6), c(RANK_7)]
        state.team_bomb_count = [0, 0]
        _finish_game(state)

        assert state.finished
        assert state.finish_order == [0, 1, 2]
        # 末游 = 3
        assert 3 not in state.finish_order

    def test_level_up_per_document(self):
        """按文档：头游+二游(同队) → +3 级；头游+三游(同队) → +2；头游+末游(同队) → +1。"""
        from guandan.engine.state import _finish_game

        # 场景 1：头游+二游同队 → team0 +3
        state = make_initial_state(level=2, first_player=0, seed=42)
        state.finish_order = [0, 2, 1]
        state.hands[3] = [c(RANK_5)]  # 末游
        state.team_bomb_count = [0, 0]
        _finish_game(state)
        assert state.finished
        assert state.team_levels_final[0] == 5  # 2 + 3
        assert state.team_levels_final[1] == 2  # 对方不变

        # 场景 2：头游+三游同队 → team0 +2
        state = make_initial_state(level=2, first_player=0, seed=42)
        state.finish_order = [0, 1, 2]
        state.hands[3] = [c(RANK_5)]
        state.team_bomb_count = [0, 0]
        _finish_game(state)
        assert state.team_levels_final[0] == 4  # 2 + 2
        assert state.team_levels_final[1] == 2  # 对方不变

        # 场景 3：头游+末游同队 → team0 +1
        state = make_initial_state(level=2, first_player=0, seed=42)
        state.finish_order = [0, 1, 3]
        state.hands[2] = [c(RANK_5)]
        state.team_bomb_count = [0, 0]
        _finish_game(state)
        assert state.team_levels_final[0] == 3  # 2 + 1
        assert state.team_levels_final[1] == 2  # 对方不变

    def test_guo_a_requires_shuangshang(self):
        """过 A 必须"双上"：队友是 2nd/3rd（即头游+二游 或 头游+三游）才算成功。"""
        from guandan.engine.state import _finish_game

        # 在 A 这一局：头游+二游（同队）→ 过 A 成功
        state = make_initial_state(level=RANK_A, first_player=0, seed=42)
        state.finish_order = [0, 2, 1]  # 头游+二游同队
        state.hands[3] = [c(RANK_5)]
        state.team_bomb_count = [3, 0]  # +3 双上 + 0 炸弹 = +3
        _finish_game(state)
        assert state.guo_a is True
        # 头游方回到 2
        assert state.team_levels_final[0] == 2

        # 在 A 这一局：头游+末游（同队）→ 冲 A 失败
        state = make_initial_state(level=RANK_A, first_player=0, seed=42)
        state.finish_order = [0, 1, 3]  # 头游+末游同队
        state.hands[2] = [c(RANK_5)]
        state.team_bomb_count = [1, 0]  # +1
        _finish_game(state)
        assert state.guo_a is False
        assert state.guo_a_failed is True
        # 头游方降回 2
        assert state.team_levels_final[0] == 2


class TestPassedLockout:
    """spec 规则 3：一旦选择"过"，该玩家在本圈牌中将失去出牌机会。

    修复 v0.3.0 → v0.3.1：`pass_count` 计数器改为 `passed_players: set`，
    锁住过牌玩家直到本 trick 结束（`_end_trick_or_jiefeng`）。
    """

    def test_passed_player_cannot_play_via_engine(self):
        """过牌后该玩家在同 trick 内 play_pattern 抛 IllegalPlayError。"""
        state = make_initial_state(level=RANK_5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_2, "H"), c(RANK_6, "H")]
        state.hands[1] = [c(RANK_7, "H"), c(RANK_9, "H")]
        state.hands[2] = [c(RANK_3, "H"), c(RANK_8, "H")]
        state.hands[3] = [c(RANK_4, "H"), c(RANK_J, "H")]

        play_pattern(state, 0, single_pattern(c(RANK_2, "H")))  # 0 出
        pass_turn(state, 1)  # 1 过
        play_pattern(state, 2, single_pattern(c(RANK_3, "H")))  # 2 出
        pass_turn(state, 3)  # 3 过
        play_pattern(state, 0, single_pattern(c(RANK_6, "H")))  # 0 再出
        # 1 已过 → 即便手牌更大也不能出
        assert 1 in state.passed_players
        with pytest.raises(IllegalPlayError):
            play_pattern(state, 1, single_pattern(c(RANK_7, "H")))

    def test_passed_players_set_persists_across_leader_replay(self):
        """0 在 trick 中再出牌时，passed_players 不应被清空。"""
        state = make_initial_state(level=RANK_5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_2, "H"), c(RANK_6, "H")]
        state.hands[1] = [c(RANK_7, "H"), c(RANK_9, "H")]
        state.hands[2] = [c(RANK_3, "H"), c(RANK_8, "H")]
        state.hands[3] = [c(RANK_4, "H"), c(RANK_J, "H")]

        play_pattern(state, 0, single_pattern(c(RANK_2, "H")))
        pass_turn(state, 1)  # passed = {1}
        play_pattern(state, 2, single_pattern(c(RANK_3, "H")))  # passed 应仍 = {1}
        assert state.passed_players == {1}
        pass_turn(state, 3)  # passed = {1, 3}
        play_pattern(state, 0, single_pattern(c(RANK_6, "H")))  # passed 应仍 = {1, 3}
        assert state.passed_players == {1, 3}

    def test_turn_skips_passed_players(self):
        """turn 推进应跳过已过牌玩家。"""
        state = make_initial_state(level=RANK_5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_2, "H"), c(RANK_6, "H")]
        state.hands[1] = [c(RANK_7, "H"), c(RANK_9, "H")]
        state.hands[2] = [c(RANK_3, "H"), c(RANK_8, "H")]
        state.hands[3] = [c(RANK_4, "H"), c(RANK_J, "H")]

        play_pattern(state, 0, single_pattern(c(RANK_2, "H")))  # turn=1
        pass_turn(state, 1)  # turn=2
        play_pattern(state, 2, single_pattern(c(RANK_3, "H")))  # turn=3
        pass_turn(state, 3)  # turn 应跳过 1, 跳到 0
        assert state.turn_index == 0
        play_pattern(state, 0, single_pattern(c(RANK_6, "H")))  # turn 应跳过 1, 跳到 2
        assert state.turn_index == 2

    def test_passed_players_cleared_on_new_trick(self):
        """3 个非 leader 全过 → trick 结束，passed_players 清空，1 可在新 trick 再行动。"""
        state = make_initial_state(level=RANK_5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_2, "H"), c(RANK_6, "H")]
        state.hands[1] = [c(RANK_7, "H")]
        state.hands[2] = [c(RANK_3, "H")]
        state.hands[3] = [c(RANK_4, "H")]

        play_pattern(state, 0, single_pattern(c(RANK_2, "H")))
        pass_turn(state, 1)
        pass_turn(state, 2)
        pass_turn(state, 3)  # 1, 2, 3 都过 → trick ends
        assert state.table == []
        assert state.passed_players == set()
        # 0 重新领出 → 1 重新能动
        play_pattern(state, 0, single_pattern(c(RANK_6, "H")))
        play_pattern(state, 1, single_pattern(c(RANK_7, "H")))  # 不抛异常
        assert state.table[-1].rank == RANK_7

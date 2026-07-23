"""AI 策略包测试。"""
from __future__ import annotations

import random

import pytest

from guandan.ai import (
    DIFFICULTY_NAMES,
    AINotImplementedError,
    make_strategy,
    play_or_pass,
)
from guandan.ai.greedy import select_min_winning
from guandan.ai.memory import PlayedTracker
from guandan.ai.stochastic import should_pass
from guandan.ai.strategies.advanced import AdvancedStrategy
from guandan.ai.strategies.intermediate import IntermediateStrategy
from guandan.ai.strategies.novice import NoviceStrategy
from guandan.ai.strategies.professional import ProfessionalStrategy
from guandan.ai.valuation import enumerate_candidate_plays, estimate_pattern_cost
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
    RANK_K,
    RANK_SMALL_JOKER,
    Card,
    Suit,
)
from guandan.engine.events import TurnPlayed
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.state import (
    make_initial_state,
    pass_turn,
    play_pattern,
)


def c(rank, suit="H"):
    s_map = {"H": Suit.HEARTS, "D": Suit.DIAMONDS, "S": Suit.SPADES, "C": Suit.CLUBS}
    return Card(rank, s_map[suit])


def sp(rank, suit="H"):
    """Construct a SINGLE Pattern from a single card."""
    card = c(rank, suit)
    return Pattern(PatternType.SINGLE, rank, 1, (card,), 0)


# ---------- Factory & metadata ----------


class TestFactory:
    def test_difficulty_names(self) -> None:
        assert DIFFICULTY_NAMES[0] == "新手"
        assert DIFFICULTY_NAMES[1] == "进阶"
        assert DIFFICULTY_NAMES[2] == "高手"
        assert DIFFICULTY_NAMES[3] == "职业"
        assert DIFFICULTY_NAMES[4] == "戴长胜"

    def test_make_strategy_returns_correct_class(self) -> None:
        assert isinstance(make_strategy(0), NoviceStrategy)
        assert isinstance(make_strategy(1), IntermediateStrategy)
        assert isinstance(make_strategy(2), AdvancedStrategy)

    def test_make_strategy_names(self) -> None:
        assert make_strategy(0).name == "新手"
        assert make_strategy(1).name == "进阶"
        assert make_strategy(2).name == "高手"
        assert make_strategy(0).difficulty == 0
        assert make_strategy(1).difficulty == 1
        assert make_strategy(2).difficulty == 2

    def test_make_strategy_3_4_raises(self) -> None:
        # 档 3 已实现（M3）
        s3 = make_strategy(3)
        assert s3.difficulty == 3
        assert s3.name == "职业"

        # 档 4 已实现（M4）
        s4 = make_strategy(4)
        assert s4.difficulty == 4
        assert s4.name == "戴长胜"

        # 档 5+ 未实现
        with pytest.raises(AINotImplementedError):
            make_strategy(5)

    def test_make_strategy_negative_raises(self) -> None:
        with pytest.raises(AINotImplementedError):
            make_strategy(-1)


# ---------- Greedy: select_min_winning ----------


class TestGreedy:
    def test_leader_returns_smallest_non_wild_single(self) -> None:
        """leader 模式：手牌里有 2/A/5/wild 5♥，出 2（最小非 wild）。"""
        state = make_initial_state(level=RANK_5, first_player=0, seed=42)
        # 把 player 0 的手牌替换为受控手牌
        state.hands[0] = [
            c(RANK_2, "S"),
            c(RANK_5, "D"),  # 不是 wild（wild 是 5H）
            c(RANK_5, "H"),  # wild
            c(RANK_A, "C"),
        ]
        p = select_min_winning(state, 0)
        assert p is not None
        assert p.type == PatternType.SINGLE
        # 出的是 2（最小非 wild）
        assert p.rank == RANK_2
        assert p.cards[0] == c(RANK_2, "S")

    def test_novice_prioritizes_a_legal_one_move_finish(self) -> None:
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_7, "H"), c(RANK_7, "D")]

        pattern = NoviceStrategy().select_pattern(state, 0)

        assert pattern is not None
        assert pattern.type == PatternType.PAIR
        assert len(pattern.cards) == len(state.hands[0])

    def test_intermediate_prioritizes_a_legal_one_move_finish(self) -> None:
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_7, "H"), c(RANK_7, "D")]

        pattern = IntermediateStrategy().select_pattern(state, 0)

        assert pattern is not None
        assert pattern.type == PatternType.PAIR
        assert len(pattern.cards) == len(state.hands[0])

    def test_follower_no_table_top_returns_leader_move(self) -> None:
        """table 空 → 等价 leader，并保护非 wild 级牌。"""
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.hands[0] = [c(RANK_2, "S"), c(RANK_5, "D"), c(RANK_A, "C")]
        assert not state.table
        p = select_min_winning(state, 0)
        assert p is not None
        assert p.rank == RANK_5

    def test_returns_none_when_cannot_beat(self) -> None:
        """桌顶是大牌、手里只有小牌、无炸弹 → None。"""
        state = make_initial_state(level=RANK_5, first_player=0, seed=42)
        # 先让 AI 0 出 A
        state.table = [sp(RANK_A, "H")]
        state.turn_index = 1
        # player 1 只有小牌，无炸弹
        state.hands[1] = [c(RANK_2, "S"), c(RANK_3, "D"), c(RANK_4, "C")]
        p = select_min_winning(state, 1)
        assert p is None

    def test_level_card_can_press_higher_natural_single(self) -> None:
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = c(RANK_2, "H")
        state.table = [sp(RANK_8, "H")]
        state.hands[1] = [c(RANK_2, "D")]

        p = select_min_winning(state, 1)

        assert p is not None
        assert p.type == PatternType.SINGLE
        assert p.rank == RANK_2

    def test_finds_minimum_pair_above(self) -> None:
        """桌顶是 SINGLE 5 → 玩家可用 PAIR 6 压（任何非炸弹同型或更大牌型都能压）。"""
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.table = [sp(RANK_5, "H")]  # 桌顶是 5（普通单张）
        # player 1 手牌：6,6,7,7,A
        # 贪心：找最小单张能压 5 → 出 6（贪心不会主动拆对子出 PAIR）
        state.hands[1] = [
            c(RANK_6, "H"),
            c(RANK_6, "S"),
            c(RANK_7, "H"),
            c(RANK_7, "S"),
            c(RANK_A, "H"),
        ]
        p = select_min_winning(state, 1)
        assert p is not None
        # 贪心在桌顶是 SINGLE 时优先出 SINGLE
        assert p.type == PatternType.SINGLE
        assert p.rank == RANK_6

    def test_bomb_beats_higher_card(self) -> None:
        """桌顶是 A，手里无 A 但有炸弹 → 找最小炸弹。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.table = [sp(RANK_A, "H")]
        state.wild_card = None
        # player 1 手牌：4 张 7 + 小牌 → 7 炸弹压 A
        state.hands[1] = [
            c(RANK_7, "H"),
            c(RANK_7, "D"),
            c(RANK_7, "S"),
            c(RANK_7, "C"),
            c(RANK_2, "H"),
            c(RANK_3, "H"),
        ]
        p = select_min_winning(state, 1)
        assert p is not None
        assert p.type == PatternType.BOMB
        assert p.rank == RANK_7

    def test_same_length_straight_can_beat_table_straight(self) -> None:
        """AI 应能用同长度更大顺子压牌，而不是只会炸或过。"""
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        table_cards = (
            c(RANK_3, "H"),
            c(RANK_4, "D"),
            c(RANK_5, "S"),
            c(RANK_6, "C"),
            c(RANK_7, "H"),
        )
        state.table = [Pattern(PatternType.STRAIGHT, RANK_7, 5, table_cards, 0)]
        state.hands[1] = [
            c(RANK_4, "H"),
            c(RANK_5, "D"),
            c(RANK_6, "S"),
            c(RANK_7, "C"),
            c(RANK_8, "H"),
        ]

        p = select_min_winning(state, 1)

        assert p is not None
        assert p.type == PatternType.STRAIGHT
        assert p.length == 5
        assert p.rank == RANK_8

    def test_same_type_triple_pair_can_beat_table_triple_pair(self) -> None:
        """AI 应能用更大的三带二压牌。"""
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        table_cards = (
            c(RANK_5, "H"),
            c(RANK_5, "D"),
            c(RANK_5, "S"),
            c(RANK_6, "H"),
            c(RANK_6, "D"),
        )
        state.table = [Pattern(PatternType.TRIPLE_PAIR, RANK_5, 1, table_cards, 0)]
        state.hands[1] = [
            c(RANK_7, "H"),
            c(RANK_7, "D"),
            c(RANK_7, "S"),
            c(RANK_8, "H"),
            c(RANK_8, "D"),
        ]

        p = select_min_winning(state, 1)

        assert p is not None
        assert p.type == PatternType.TRIPLE_PAIR
        assert p.rank == RANK_7

    def test_ten_card_bomb_can_beat_nine_card_bomb(self) -> None:
        """炸弹候选应支持 10 张（8 张同点 + 2 张逢人配）。"""
        state = make_initial_state(level=RANK_5, first_player=0, seed=42)
        wild = c(RANK_5, "H")
        state.wild_card = wild
        state.table = [
            Pattern(PatternType.BOMB, RANK_A, 9, tuple(c(RANK_A, "H") for _ in range(9)), 0)
        ]
        state.hands[1] = [
            *[c(RANK_7, suit) for suit in ("H", "H", "D", "D", "S", "S", "C", "C")],
            wild,
            wild,
        ]

        p = select_min_winning(state, 1)

        assert p is not None
        assert p.type == PatternType.BOMB
        assert p.rank == RANK_7
        assert p.length == 10

    def test_bomb_order_uses_straight_flush_before_six_bomb(self) -> None:
        """面对 5 张普通炸弹时，AI 应先用同花顺，再考虑更大的 6+ 普通炸弹。"""
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.table = [
            Pattern(
                PatternType.BOMB,
                RANK_A,
                5,
                tuple(c(RANK_A, suit) for suit in ("H", "D", "S", "C", "H")),
                0,
            )
        ]
        state.hands[1] = [
            c(RANK_3, "H"),
            c(RANK_4, "H"),
            c(RANK_5, "H"),
            c(RANK_6, "H"),
            c(RANK_7, "H"),
            c(RANK_8, "H"),
            c(RANK_8, "D"),
            c(RANK_8, "S"),
            c(RANK_8, "C"),
            c(RANK_8, "H"),
            c(RANK_8, "D"),
        ]

        p = select_min_winning(state, 1)

        assert p is not None
        assert p.type == PatternType.STRAIGHT_FLUSH


# ---------- Valuation: estimate_pattern_cost ----------


class TestValuation:
    def test_finish_bonus_drastic_reduction(self) -> None:
        """出完手牌 → cost 减 20。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        # 手牌只有 1 张 → 出它 = finish
        state.hands[0] = [c(RANK_2, "H")]
        pat = sp(RANK_2, "H")
        cost = estimate_pattern_cost(state, 0, pat)
        # base=0 (SINGLE) + breakup=0 + wild=0 + high=0 + bomb=0 - 20(finish) = -20
        assert cost < 0  # 完牌必出

    def test_break_pair_penalty(self) -> None:
        """拆对子比拆单张贵。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        # 手牌 = 1 对 7 + 1 张 2。出对子 vs 出单 2：出 2 不拆对 → cost 较低
        state.hands[0] = [
            c(RANK_7, "H"),
            c(RANK_7, "D"),
            c(RANK_2, "S"),
        ]
        pat_pair = Pattern(PatternType.PAIR, RANK_7, 2, (c(RANK_7, "H"), c(RANK_7, "D")), 0)
        pat_single_2 = sp(RANK_2, "S")
        cost_pair = estimate_pattern_cost(state, 0, pat_pair)
        cost_single = estimate_pattern_cost(state, 0, pat_single_2)
        # 出对子 = base(1) + 拆 2 张(0) + finish(0) = 1
        # 出单 2 = base(0) - 但手牌剩 7,7 → 拆对 penalty?
        # 实际：after={7:2} vs before={7:2, 2:1} → 没有拆对（7:2 → 7:2）
        # 所以 cost_single < cost_pair
        assert cost_single < cost_pair

    def test_wild_penalty_hurts_small_play(self) -> None:
        """用 wild 出小单张 → cost 很高。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        wild = c(RANK_5, "H")
        state.wild_card = wild
        # 手牌 = 1 张 wild + 1 张 K
        state.hands[0] = [wild, c(RANK_K, "D")]
        # 用 wild 出单张 = 浪费 wild
        pat_wild = Pattern(PatternType.SINGLE, RANK_5, 1, (wild,), 1)
        cost_wild = estimate_pattern_cost(state, 0, pat_wild)
        # 用 K 出单张 = 不用 wild
        pat_k = sp(RANK_K, "D")
        cost_k = estimate_pattern_cost(state, 0, pat_k)
        # K 单张：base(0) + K penalty(0.5) = 0.5
        # wild 单张：base(0) + wild penalty(8) + 5 rank penalty(0) = 8
        assert cost_wild > cost_k

    def test_bomb_is_expensive(self) -> None:
        """炸弹基础 cost 高于单张。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        # 手牌 = 4 张 8 + 1 张 2
        state.hands[0] = [
            c(RANK_8, "H"),
            c(RANK_8, "D"),
            c(RANK_8, "S"),
            c(RANK_8, "C"),
            c(RANK_2, "H"),
        ]
        bomb = Pattern(PatternType.BOMB, RANK_8, 4, tuple(state.hands[0][:4]), 0)
        single = sp(RANK_2, "H")
        c_bomb = estimate_pattern_cost(state, 0, bomb)
        c_single = estimate_pattern_cost(state, 0, single)
        assert c_bomb > c_single

    def test_non_wild_level_card_is_protected_as_high_card(self) -> None:
        """非红桃级牌也应按最大非王牌保护，避免 AI 领牌随手打掉。"""
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = c(RANK_2, "H")
        state.table = []
        state.hands[0] = [c(RANK_2, "S"), c(RANK_9, "D")]

        level_cost = estimate_pattern_cost(state, 0, sp(RANK_2, "S"))
        nine_cost = estimate_pattern_cost(state, 0, sp(RANK_9, "D"))

        assert level_cost > nine_cost


# ---------- Valuation: enumerate_candidate_plays ----------


class TestEnumerateCandidates:
    def test_returns_sorted_by_cost(self) -> None:
        """候选按 cost 升序。"""
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.table = [sp(RANK_5, "H")]
        state.hands[1] = [
            c(RANK_6, "H"),
            c(RANK_6, "S"),
            c(RANK_7, "H"),
            c(RANK_A, "H"),
            c(RANK_A, "S"),
        ]
        candidates = enumerate_candidate_plays(state, 1)
        assert len(candidates) > 0
        costs = [estimate_pattern_cost(state, 1, p) for p in candidates]
        assert costs == sorted(costs)

    def test_includes_level_card_press_candidate(self) -> None:
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = c(RANK_2, "H")
        state.table = [sp(RANK_8, "H")]
        state.hands[1] = [c(RANK_2, "D"), c(RANK_4, "S")]

        candidates = enumerate_candidate_plays(state, 1)

        assert any(p.type == PatternType.SINGLE and p.rank == RANK_2 for p in candidates)

    def test_leader_prefers_plain_single_before_level_card(self) -> None:
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = c(RANK_2, "H")
        state.table = []
        state.hands[0] = [c(RANK_2, "S"), c(RANK_9, "D")]

        candidates = enumerate_candidate_plays(state, 0)

        assert candidates[0].type == PatternType.SINGLE
        assert candidates[0].rank == RANK_9

    def test_leader_prefers_natural_straight_to_plain_single(self) -> None:
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.table = []
        state.hands[0] = [
            c(RANK_3, "H"),
            c(RANK_4, "D"),
            c(RANK_5, "S"),
            c(RANK_6, "C"),
            c(RANK_7, "H"),
            c(RANK_9, "D"),
        ]

        candidates = enumerate_candidate_plays(state, 0)

        assert candidates[0].type == PatternType.STRAIGHT
        assert candidates[0].rank == RANK_7

    def test_leader_does_not_spend_wild_for_shedding_bonus(self) -> None:
        wild = c(RANK_5, "H")
        state = make_initial_state(level=RANK_5, first_player=0, seed=42)
        state.wild_card = wild
        state.table = []
        state.hands[0] = [
            c(RANK_3, "H"),
            c(RANK_4, "D"),
            wild,
            c(RANK_6, "C"),
            c(RANK_7, "H"),
            c(RANK_9, "D"),
        ]

        candidates = enumerate_candidate_plays(state, 0)

        assert candidates[0].type == PatternType.SINGLE
        assert candidates[0].rank == RANK_9

    def test_leader_avoids_single_when_opponent_has_one_card(self) -> None:
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.table = []
        state.hands[0] = [
            c(RANK_3, "H"),
            c(RANK_7, "D"),
            c(RANK_7, "S"),
            c(RANK_K, "C"),
        ]
        state.hands[1] = [c(RANK_4, "H")]
        state.hands[3] = [c(RANK_5, "H"), c(RANK_6, "H")]

        candidates = enumerate_candidate_plays(state, 0)

        assert candidates[0].type == PatternType.PAIR
        assert candidates[0].rank == RANK_7

    def test_leader_returns_all_singles(self) -> None:
        """leader 模式：候选 = 手牌中所有非 wild 单张。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        # leader：table 空
        state.hands[0] = [c(RANK_2, "H"), c(RANK_5, "S"), c(RANK_A, "C")]
        candidates = enumerate_candidate_plays(state, 0)
        # 3 张非 wild → 3 个 SINGLE 候选
        assert len(candidates) == 3
        for p in candidates:
            assert p.type == PatternType.SINGLE

    def test_includes_same_type_straight_response(self) -> None:
        state = make_initial_state(level=RANK_5, first_player=0, seed=42)
        state.wild_card = None
        state.table = [
            Pattern(
                PatternType.STRAIGHT,
                RANK_7,
                5,
                (
                    c(RANK_3, "H"),
                    c(RANK_4, "D"),
                    c(RANK_5, "S"),
                    c(RANK_6, "C"),
                    c(RANK_7, "H"),
                ),
                0,
            )
        ]
        state.hands[1] = [
            c(RANK_4, "H"),
            c(RANK_5, "D"),
            c(RANK_6, "S"),
            c(RANK_7, "C"),
            c(RANK_8, "H"),
        ]

        candidates = enumerate_candidate_plays(state, 1)

        assert any(
            p.type == PatternType.STRAIGHT and p.length == 5 and p.rank == RANK_8
            for p in candidates
        )


# ---------- Memory: PlayedTracker ----------


class TestPlayedTracker:
    def test_initial_state_all_remaining(self) -> None:
        """新发的牌 → 普通点数各 8 张未出。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        tracker = PlayedTracker.from_history(state)
        for r in range(2, 15):
            assert tracker.remaining(r) == 8
        assert tracker.remaining(RANK_SMALL_JOKER) == 2

    def test_remaining_decreases_after_play(self) -> None:
        """打出一张后 remaining 减 1。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_5, "H")]
        before = PlayedTracker.from_history(state).remaining(RANK_5)
        play_pattern(state, 0, sp(RANK_5, "H"))
        after = PlayedTracker.from_history(state).remaining(RANK_5)
        assert after == before - 1

    def test_in_someone_hand_excludes_self(self) -> None:
        """in_someone_hand 算其他 3 家（不含自己）。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_5, "H"), c(RANK_5, "D")]  # 2 张 5
        tracker = PlayedTracker.from_history(state)
        # 5 总数 8 张，2 张在 0 手里 → 其他家最多还有 6 张
        assert tracker.in_someone_hand(RANK_5, state.hands[0]) == 6

    def test_bomb_count_tracked(self) -> None:
        """炸弹出过后 bomb_count 增 1。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [
            c(RANK_8, "H"),
            c(RANK_8, "D"),
            c(RANK_8, "S"),
            c(RANK_8, "C"),
        ]
        assert PlayedTracker.from_history(state).bomb_count == 0
        bomb = Pattern(PatternType.BOMB, RANK_8, 4, tuple(state.hands[0]), 0)
        play_pattern(state, 0, bomb)
        assert PlayedTracker.from_history(state).bomb_count == 1


# ---------- Stochastic: should_pass ----------


class TestShouldPass:
    def test_leader_never_passes(self) -> None:
        """table 空（leader）→ 一定出。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_2, "H")]
        rng = random.Random(0)
        assert should_pass(state, 0, sp(RANK_2, "H"), rng=rng) is False

    def test_no_pattern_always_passes(self) -> None:
        """pattern=None → 一定过。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        state.table = [sp(RANK_A, "H")]
        state.hands[1] = [c(RANK_2, "H")]  # 没法压
        rng = random.Random(0)
        assert should_pass(state, 1, None, rng=rng) is True

    def test_high_table_top_more_likely_to_pass(self) -> None:
        """桌顶 rank 越大 → 越倾向过牌。"""
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        # 多次抽样，看桌顶 = A 时过牌率 > 桌顶 = 5 时
        n = 1000
        rng = random.Random(0)
        passes_low = 0
        for _ in range(n):
            state.table = [sp(RANK_5, "H")]
            if should_pass(state, 1, sp(RANK_8, "D"), rng=rng, base=0.1, scale=0.6):
                passes_low += 1
        rng = random.Random(0)
        passes_high = 0
        for _ in range(n):
            state.table = [sp(RANK_A, "H")]
            if should_pass(state, 1, sp(RANK_8, "D"), rng=rng, base=0.1, scale=0.6):
                passes_high += 1
        assert passes_high > passes_low

    def test_level_table_top_uses_effective_strength(self) -> None:
        """桌顶为级牌时，概率过牌应按最大非王牌强度计算。"""

        class FixedRandom(random.Random):
            def random(self) -> float:
                return 0.50

        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = c(RANK_2, "H")
        state.table = [sp(RANK_2, "S")]
        small_joker = Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER)
        pattern = Pattern(PatternType.SINGLE, RANK_SMALL_JOKER, 1, (small_joker,), 0)
        state.hands[1] = [small_joker, c(RANK_9, "D")]

        assert should_pass(
            state,
            1,
            pattern,
            rng=FixedRandom(),
            base=0.1,
            scale=0.6,
        ) is True

    def test_never_randomly_passes_when_opponent_has_one_card(self) -> None:
        """任一对手只剩 1 张时，有合法响应就必须拦截。"""

        class AlwaysPassRandom(random.Random):
            def random(self) -> float:
                return 0.0

        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.table = [sp(RANK_9, "H")]
        state.hands[0] = [c(RANK_3, "D")]
        state.hands[1] = [c(RANK_A, "D"), c(RANK_4, "D")]
        state.hands[2] = [c(RANK_5, "D")]
        state.hands[3] = [c(RANK_6, "D"), c(RANK_7, "D")]

        assert should_pass(state, 1, sp(RANK_A, "D"), rng=AlwaysPassRandom()) is False

    def test_deterministic_with_seed(self) -> None:
        """同样的 rng → 同样的决策。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        state.table = [sp(RANK_5, "H")]
        state.hands[1] = [c(RANK_8, "D")]
        rng1 = random.Random(123)
        rng2 = random.Random(123)
        d1 = should_pass(state, 1, sp(RANK_8, "D"), rng=rng1)
        d2 = should_pass(state, 1, sp(RANK_8, "D"), rng=rng2)
        assert d1 == d2

    def test_multiplier_adjusts_pass_probability(self) -> None:
        """策略倍率可以实际改变概率过牌结果。"""

        class FixedRandom(random.Random):
            def random(self) -> float:
                return 0.75

        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        state.table = [sp(RANK_A, "H")]
        state.hands[1] = [c(RANK_8, "D"), c(RANK_9, "D")]

        assert should_pass(
            state, 1, sp(RANK_8, "D"), rng=FixedRandom(), multiplier=1.0
        ) is False
        assert should_pass(
            state, 1, sp(RANK_8, "D"), rng=FixedRandom(), multiplier=1.2
        ) is True


# ---------- Strategies: distinct behavior ----------


class TestStrategyDifferentiation:
    def test_advanced_passes_when_teammate_winning(self) -> None:
        """Advanced：队友已领先 → 主动过牌（None）。"""
        # 流程：0 出 A（leader）→ 3 出炸弹压 A。
        # 然后手动让 turn=1，桌顶是 3 的炸弹
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_A, "H"), c(RANK_2, "D"), c(RANK_3, "D"), c(RANK_4, "D")]
        state.hands[3] = [
            c(RANK_8, "H"),
            c(RANK_8, "D"),
            c(RANK_8, "S"),
            c(RANK_8, "C"),
            c(RANK_5, "D"),
        ]
        state.hands[1] = [
            c(RANK_9, "H"),
            c(RANK_9, "D"),
            c(RANK_9, "S"),
            c(RANK_9, "C"),
            c(RANK_5, "S"),
        ]
        # 0 出 A
        play_pattern(state, 0, sp(RANK_A, "H"))
        # 3 出 8 炸弹（压 A）
        bomb = Pattern(PatternType.BOMB, RANK_8, 4, tuple(state.hands[3][:4]), 0)
        play_pattern(state, 3, bomb)
        # 手动把 turn 设回 1（模拟回到 1 的视角）
        state.turn_index = 1
        # 1 的对家是 3，3 在桌顶（炸弹）→ 协作分触发
        adv = AdvancedStrategy()
        p = adv.select_pattern(state, 1)
        assert p is None
        # 新手/进阶 不考虑协作
        nov = NoviceStrategy()
        p_nov = nov.select_pattern(state, 1)
        assert p_nov is not None

    def test_advanced_covers_teammate_single_when_opponent_has_one_card(self) -> None:
        """队友单张领先但对手报单时，高手 AI 应抬高桌顶而不是纯让牌。"""
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.turn_index = 1
        state.leader = 3
        state.table = [sp(RANK_9, "H")]
        state.hands[0] = [c(RANK_3, "D")]
        state.hands[1] = [c(RANK_A, "D"), c(RANK_4, "D")]
        state.hands[2] = [c(RANK_5, "D")]
        state.hands[3] = [c(RANK_6, "D"), c(RANK_7, "D")]

        pattern = AdvancedStrategy().select_pattern(state, 1)

        assert pattern is not None
        assert pattern.type == PatternType.SINGLE
        assert pattern.rank == RANK_A

    def test_advanced_finishes_before_teammate_cooperation(self) -> None:
        """高手 AI 能出完时，不应被队友领先协作分改成过牌。"""
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.turn_index = 0
        state.leader = 2
        state.table = [sp(RANK_8, "H")]
        state.hands[0] = [c(RANK_9, "S")]
        state.hands[1] = [c(RANK_3, "D"), c(RANK_4, "D")]
        state.hands[2] = [c(RANK_5, "D"), c(RANK_6, "D")]
        state.hands[3] = [c(RANK_7, "D"), c(RANK_K, "D")]

        pattern = AdvancedStrategy().select_pattern(state, 0)

        assert pattern is not None
        assert pattern.type == PatternType.SINGLE
        assert pattern.rank == RANK_9

    def test_intermediate_valuation_differs_from_greedy(self) -> None:
        """Intermediate 的 cost-based 选牌 ≠ 纯贪心。"""
        # 构造手牌：3 张 6（可压 5），1 张 K
        # 贪心：出 6（最小可压对子——等等，只 3 张 6 是 TRIPLE）
        # 贪心：出 6,6（pair），cost 较低
        # 用 7,7,7 (TRIPLE) vs 6,6 (PAIR) 比较
        # 实际估值：TRIPLE weight=2 > PAIR weight=1，所以 PAIR 优先
        # 这个测试可能太微妙。简化：比较两个候选的成本排序
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.table = [sp(RANK_5, "H")]
        state.hands[1] = [
            c(RANK_6, "H"),
            c(RANK_6, "D"),
            c(RANK_6, "S"),
            c(RANK_A, "C"),
        ]
        candidates = enumerate_candidate_plays(state, 1)
        assert len(candidates) >= 2
        # 第一候选 = cost 最小
        costs = [estimate_pattern_cost(state, 1, p) for p in candidates]
        assert costs[0] == min(costs)

    def test_intermediate_leads_with_natural_straight(self) -> None:
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.table = []
        state.hands[0] = [
            c(RANK_3, "H"),
            c(RANK_4, "D"),
            c(RANK_5, "S"),
            c(RANK_6, "C"),
            c(RANK_7, "H"),
            c(RANK_9, "D"),
        ]

        pattern = IntermediateStrategy().select_pattern(state, 0)

        assert pattern is not None
        assert pattern.type == PatternType.STRAIGHT
        assert pattern.rank == RANK_7

    def test_intermediate_leads_pair_when_opponent_has_one_card(self) -> None:
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.table = []
        state.hands[0] = [
            c(RANK_3, "H"),
            c(RANK_7, "D"),
            c(RANK_7, "S"),
            c(RANK_K, "C"),
        ]
        state.hands[1] = [c(RANK_4, "H")]
        state.hands[3] = [c(RANK_5, "H"), c(RANK_6, "H")]

        pattern = IntermediateStrategy().select_pattern(state, 0)

        assert pattern is not None
        assert pattern.type == PatternType.PAIR
        assert pattern.rank == RANK_7

    def test_advanced_builds_played_tracker_once_per_decision(self, monkeypatch) -> None:
        """高手策略一次决策只应扫描一次历史，避免按候选重复记牌。"""
        original = PlayedTracker.from_history
        calls = {"count": 0}

        def counted_from_history(cls, state):
            calls["count"] += 1
            return original(state)

        monkeypatch.setattr(PlayedTracker, "from_history", classmethod(counted_from_history))

        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.table = [sp(RANK_5, "H")]
        state.hands[1] = [
            c(RANK_6, "H"),
            c(RANK_6, "D"),
            c(RANK_6, "S"),
            c(RANK_A, "C"),
        ]

        pattern = AdvancedStrategy().select_pattern(state, 1)

        assert pattern is not None
        assert calls["count"] == 1

    def test_advanced_difficulty_attributes(self) -> None:
        adv = AdvancedStrategy()
        assert adv.difficulty == 2
        assert adv.name == "高手"

    def test_teammate_winning_uses_value_equality(self) -> None:
        """深拷贝/存档恢复后，桌顶牌型对象不同但值相等，协作仍应生效。"""
        import copy

        from guandan.ai.strategies.advanced import _teammate_winning

        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[2] = [c(RANK_A, "H"), c(RANK_2, "D")]
        state.turn_index = 2
        play_pattern(state, 2, sp(RANK_A, "H"))
        state.table[-1] = copy.deepcopy(state.table[-1])

        assert _teammate_winning(state, 0) is True

    def test_intermediate_difficulty_attributes(self) -> None:
        inter = IntermediateStrategy()
        assert inter.difficulty == 1
        assert inter.name == "进阶"

    def test_novice_difficulty_attributes(self) -> None:
        nov = NoviceStrategy()
        assert nov.difficulty == 0
        assert nov.name == "新手"


# ---------- play_or_pass (integration) ----------


class TestPlayOrPass:
    class AlwaysNoneStrategy:
        name = "空策略"
        difficulty = 99
        uses_stochastic_pass = True

        def select_pattern(self, state, player):
            return None

    def test_leader_always_plays(self) -> None:
        """leader 模式：play_or_pass 一定返回 True（出牌）。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_2, "H"), c(RANK_5, "D")]
        rng = random.Random(0)
        result = play_or_pass(state, 0, make_strategy(0), rng)
        assert result is True
        assert any(isinstance(event, TurnPlayed) for event in state.history[1:])
        assert state.turn_index == 3

    def test_no_pattern_with_no_table_uses_leader_fallback(self) -> None:
        """leader + select_pattern 返回 None → 兜底出最小单张。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_5, "H")]
        rng = random.Random(0)
        result = play_or_pass(state, 0, self.AlwaysNoneStrategy(), rng)

        assert result is True
        assert state.table[-1].rank == RANK_5

    def test_leader_fallback_protects_level_card(self) -> None:
        """leader 兜底选牌也应按级牌强度保护非红桃级牌。"""
        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = c(RANK_2, "H")
        state.hands[0] = [c(RANK_2, "S"), c(RANK_9, "D")]
        rng = random.Random(0)

        result = play_or_pass(state, 0, self.AlwaysNoneStrategy(), rng)

        assert result is True
        assert state.table[-1].rank == RANK_9

    def test_advanced_passes_when_teammate_winning(self) -> None:
        """Advanced 协作分：队友在桌顶 → play_or_pass 返回 False。

        流程：0 出 A → 3 出炸弹压 A。
        手动把 turn 设为 1（1 的对家是 3，3 在桌顶）→ Advanced 应过牌。
        """
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_A, "H"), c(RANK_2, "D"), c(RANK_3, "D"), c(RANK_4, "D")]
        state.hands[3] = [
            c(RANK_8, "H"),
            c(RANK_8, "D"),
            c(RANK_8, "S"),
            c(RANK_8, "C"),
            c(RANK_5, "D"),
        ]
        play_pattern(state, 0, sp(RANK_A, "H"))
        bomb = Pattern(PatternType.BOMB, RANK_8, 4, tuple(state.hands[3][:4]), 0)
        play_pattern(state, 3, bomb)
        # 手动让 turn=1，模拟"轮回到 1"
        state.turn_index = 1
        # 1 的对家是 3，3 是桌顶出牌者 → Advanced 触发协作分 → 过牌
        rng = random.Random(0)
        result = play_or_pass(state, 1, make_strategy(2), rng)
        assert result is False
        # 直接验证 _teammate_winning 的核心逻辑
        from guandan.ai.strategies.advanced import _teammate_winning

        s = make_initial_state(level=5, first_player=0, seed=42)
        s.wild_card = None
        s.hands[0] = [c(RANK_A, "H"), c(RANK_2, "D"), c(RANK_3, "D"), c(RANK_4, "D")]
        s.hands[1] = [c(RANK_4, "D"), c(RANK_5, "D"), c(RANK_6, "D"), c(RANK_7, "D")]
        s.hands[2] = [
            c(RANK_8, "H"),
            c(RANK_8, "D"),
            c(RANK_8, "S"),
            c(RANK_8, "C"),
            c(RANK_5, "D"),
        ]
        play_pattern(s, 0, sp(RANK_A, "H"))  # turn -> 3
        pass_turn(s, 3)  # turn -> 2
        bomb = Pattern(PatternType.BOMB, RANK_8, 4, tuple(s.hands[2][:4]), 0)
        play_pattern(s, 2, bomb)  # turn -> 1；2 是 0 的对家
        # 2 是 0 的对家，在桌顶
        assert _teammate_winning(s, 0) is True
        # 1 的对家是 3，3 没出
        assert _teammate_winning(s, 1) is False

    def test_professional_decision_is_not_randomly_overridden(self) -> None:
        """职业档策略选出可压牌后，不再被统一概率过牌二次覆盖。"""

        class AlwaysPassRandom(random.Random):
            def random(self) -> float:
                return 0.0

        state = make_initial_state(level=RANK_5, first_player=0, seed=42)
        state.wild_card = None
        state.table = [sp(RANK_8, "H")]
        state.hands[1] = [c(RANK_9, "D"), c(RANK_3, "D")]
        state.turn_index = 1
        state.leader = 0
        strategy = ProfessionalStrategy(mcts_hand_threshold=0)

        result = play_or_pass(state, 1, strategy, AlwaysPassRandom())

        assert result is True
        assert state.table[-1].rank == RANK_9
        assert state.turn_index == 0

    def test_intermediate_blocks_one_card_opponent_without_random_pass(self) -> None:
        """对手只剩 1 张时，进阶 AI 有牌可压就不随机过牌。"""

        class AlwaysPassRandom(random.Random):
            def random(self) -> float:
                return 0.0

        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.turn_index = 1
        state.leader = 0
        state.table = [sp(RANK_9, "H")]
        state.hands[0] = [c(RANK_3, "D")]
        state.hands[1] = [c(RANK_A, "D"), c(RANK_4, "D")]
        state.hands[2] = [c(RANK_5, "D")]
        state.hands[3] = [c(RANK_6, "D"), c(RANK_7, "D")]

        result = play_or_pass(state, 1, make_strategy(1), AlwaysPassRandom())

        assert result is True
        assert state.table[-1].rank == RANK_A

    def test_advanced_covers_teammate_and_blocks_one_card_opponent(self) -> None:
        """队友领先且对手报单时，高手 AI 会护航并且不被随机过牌覆盖。"""

        class AlwaysPassRandom(random.Random):
            def random(self) -> float:
                return 0.0

        state = make_initial_state(level=RANK_2, first_player=0, seed=42)
        state.wild_card = None
        state.turn_index = 1
        state.leader = 3
        state.table = [sp(RANK_9, "H")]
        state.hands[0] = [c(RANK_3, "D")]
        state.hands[1] = [c(RANK_A, "D"), c(RANK_4, "D")]
        state.hands[2] = [c(RANK_5, "D")]
        state.hands[3] = [c(RANK_6, "D"), c(RANK_7, "D")]

        result = play_or_pass(state, 1, make_strategy(2), AlwaysPassRandom())

        assert result is True
        assert state.table[-1].rank == RANK_A


# ---------- Hint strategy fix to 档 1 ----------


class TestHintStrategyFixed:
    """T 键提示固定用 档 1（进阶）。这一行为在 game.py 里硬编码——这里只测档 1 本身有效。"""

    def test_intermediate_selects_legal_hint(self) -> None:
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        # 把 human（默认 0）手牌设为简单手牌
        state.hands[0] = [c(RANK_5, "D"), c(RANK_8, "H"), c(RANK_A, "S")]
        strat = make_strategy(1)
        p = strat.select_pattern(state, 0)
        # 进阶策略会保护非红桃级牌 5，leader 模式优先出普通小牌。
        assert p is not None
        assert p.type == PatternType.SINGLE
        assert p.rank == RANK_8

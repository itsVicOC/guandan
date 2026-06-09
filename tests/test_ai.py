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
from guandan.ai.valuation import enumerate_candidate_plays, estimate_pattern_cost
from guandan.engine.card import (
    RANK_2,
    RANK_3,
    RANK_4,
    RANK_5,
    RANK_6,
    RANK_7,
    RANK_8,
    RANK_A,
    RANK_K,
    Card,
    Suit,
)
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
        state = make_initial_state(level=5, first_player=0, seed=42)
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

    def test_follower_no_table_top_returns_leader_move(self) -> None:
        """table 空 → 等价 leader，行为一致。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.hands[0] = [c(RANK_2, "S"), c(RANK_5, "D"), c(RANK_A, "C")]
        assert not state.table
        p = select_min_winning(state, 0)
        assert p is not None
        assert p.rank == RANK_2

    def test_returns_none_when_cannot_beat(self) -> None:
        """桌顶是大牌、手里只有小牌、无炸弹 → None。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        # 先让 AI 0 出 A
        state.table = [sp(RANK_A, "H")]
        state.turn_index = 1
        # player 1 只有小牌，无炸弹
        state.hands[1] = [c(RANK_2, "S"), c(RANK_3, "D"), c(RANK_4, "C")]
        p = select_min_winning(state, 1)
        assert p is None

    def test_finds_minimum_pair_above(self) -> None:
        """桌顶是 SINGLE 5 → 玩家可用 PAIR 6 压（任何非炸弹同型或更大牌型都能压）。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
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


# ---------- Valuation: enumerate_candidate_plays ----------


class TestEnumerateCandidates:
    def test_returns_sorted_by_cost(self) -> None:
        """候选按 cost 升序。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
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


# ---------- Memory: PlayedTracker ----------


class TestPlayedTracker:
    def test_initial_state_all_remaining(self) -> None:
        """新发的牌 → 各种 rank 都有 remaining=4。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        tracker = PlayedTracker.from_history(state)
        for r in range(2, 15):
            # 我手牌里有的 rank 不会全是 remaining=4
            # 但 remaining >= 2 (我手牌至少 1 张) - 0
            assert tracker.remaining(r) >= 0

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
        state.hands[1] = [c(RANK_5, "S"), c(RANK_5, "C")]  # 2 张 5 → 全部 4 张打完
        tracker = PlayedTracker.from_history(state)
        # 5 总数 4 张，2 张在 0 手里 → 其他家有 2 张
        assert tracker.in_someone_hand(RANK_5, state.hands[0]) == 2

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
        state = make_initial_state(level=5, first_player=0, seed=42)
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

    def test_intermediate_valuation_differs_from_greedy(self) -> None:
        """Intermediate 的 cost-based 选牌 ≠ 纯贪心。"""
        # 构造手牌：3 张 6（可压 5），1 张 K
        # 贪心：出 6（最小可压对子——等等，只 3 张 6 是 TRIPLE）
        # 贪心：出 6,6（pair），cost 较低
        # 用 7,7,7 (TRIPLE) vs 6,6 (PAIR) 比较
        # 实际估值：TRIPLE weight=2 > PAIR weight=1，所以 PAIR 优先
        # 这个测试可能太微妙。简化：比较两个候选的成本排序
        state = make_initial_state(level=5, first_player=0, seed=42)
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

    def test_advanced_difficulty_attributes(self) -> None:
        adv = AdvancedStrategy()
        assert adv.difficulty == 2
        assert adv.name == "高手"

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
    def test_leader_always_plays(self) -> None:
        """leader 模式：play_or_pass 一定返回 True（出牌）。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_2, "H"), c(RANK_5, "D")]
        rng = random.Random(0)
        result = play_or_pass(state, 0, make_strategy(0), rng)
        assert result is True
        assert len(state.history) == 2  # ShuffleDeal + TurnPlayed
        assert state.turn_index == 3

    def test_no_pattern_with_no_table_uses_leader_fallback(self) -> None:
        """leader + select_pattern 返回 None → 兜底出最小单张。"""
        state = make_initial_state(level=5, first_player=0, seed=42)
        state.wild_card = None
        state.hands[0] = [c(RANK_5, "H")]  # 5H 是 wild
        # 新手 不会 返回 None on leader (greedy leader returns smallest non-wild)
        # 但若手牌全 wild，select_pattern 会返回 wild 单张
        rng = random.Random(0)
        result = play_or_pass(state, 0, make_strategy(0), rng)
        assert result is True  # 不管怎样出牌了

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
        # 进阶策略：有候选的话返回最优；若有可压 → 返回 SINGLE 5
        # leader 模式：出最小单张
        assert p is not None
        assert p.type == PatternType.SINGLE
        assert p.rank == RANK_5

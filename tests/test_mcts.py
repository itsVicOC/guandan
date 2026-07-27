"""MCTS 模块测试。

测试：
1. 确定化逻辑正确性
2. UCB1 计算
3. MCTS 搜索循环
4. ProfessionalStrategy 集成
"""
from __future__ import annotations

import copy
import random
from collections import Counter

import pytest

from guandan.ai.mcts import MCTS_CONFIG
from guandan.ai.mcts.determinize import (
    PassEvidence,
    _get_all_cards_in_game,
    card_owner_likelihood,
    determinize,
)
from guandan.ai.mcts.information_set import (
    PASS_ACTION,
    InformationSetNode,
    _has_expansion_capacity,
    information_set_search,
    team_selection_score,
)
from guandan.ai.mcts.node import MCTSNode
from guandan.ai.mcts.search import (
    _evaluate_result,
    _get_legal_actions,
    _rollout_select_pattern,
    mcts_search,
    ucb1_score,
)
from guandan.ai.strategies.professional import ProfessionalStrategy
from guandan.ai.valuation import enumerate_search_candidates
from guandan.engine.card import RANK_BIG_JOKER, RANK_SMALL_JOKER, Card, Suit
from guandan.engine.deck import deal, make_deck, shuffle_deck
from guandan.engine.events import TributeReturned, TributeSent, TurnPlayed
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.state import GameState, pass_turn, play_pattern


def _make_test_state(level: int = 2, seed: int = 42) -> GameState:
    """创建测试用游戏状态。"""
    rng = random.Random(seed)
    deck = make_deck()
    shuffle_deck(deck, rng)
    hands = deal(deck)

    # 找到逢人配
    from guandan.engine.card import Suit
    wild_card = None
    for card in deck:
        if card.rank == level and card.suit == Suit.HEARTS:
            wild_card = card
            break

    state = GameState(
        level=level,
        wild_card=wild_card,
        hands=hands,
        turn_index=0,
    )
    return state


class TestDeterminize:
    """测试确定化逻辑。"""

    def test_all_cards_uses_real_joker_suits(self):
        """确定化牌池中的大小王必须保留 joker suit。"""
        cards = _get_all_cards_in_game()
        jokers = [card for card in cards if card.is_joker]

        assert len(jokers) == 4
        assert sum(1 for card in jokers if card.rank == RANK_SMALL_JOKER) == 2
        assert sum(1 for card in jokers if card.rank == RANK_BIG_JOKER) == 2

    def test_determinize_preserves_hand_sizes(self):
        """确定化后每家手牌数守恒。"""
        state = _make_test_state()
        player = 0
        rng = random.Random(42)

        # 记录原始手牌数
        original_sizes = [state.hand_size(p) for p in range(4)]

        # 确定化
        new_state = determinize(state, player, rng)

        # 验证手牌数守恒
        new_sizes = [new_state.hand_size(p) for p in range(4)]
        assert new_sizes == original_sizes
        assert Counter(card for hand in new_state.hands for card in hand) == Counter(
            _get_all_cards_in_game()
        )

    def test_determinize_preserves_player_hand(self):
        """确定化后当前玩家手牌不变。"""
        state = _make_test_state()
        player = 0
        rng = random.Random(42)

        original_hand = state.hands[player].copy()

        new_state = determinize(state, player, rng)

        # 当前玩家手牌应该完全一样
        assert sorted(new_state.hands[player], key=lambda c: (c.rank, c.suit.value)) == \
               sorted(original_hand, key=lambda c: (c.rank, c.suit.value))

    def test_determinize_randomness(self):
        """多次确定化结果不同（其他玩家手牌不同）。"""
        state = _make_test_state()
        player = 0

        rng1 = random.Random(1)
        rng2 = random.Random(2)

        new_state1 = determinize(state, player, rng1)
        new_state2 = determinize(state, player, rng2)

        # 至少有一家的手牌不同
        different = False
        for p in range(4):
            if p == player:
                continue
            if sorted(new_state1.hands[p], key=lambda c: (c.rank, c.suit.value)) != \
               sorted(new_state2.hands[p], key=lambda c: (c.rank, c.suit.value)):
                different = True
                break

        assert different, "两次确定化应该产生不同的手牌分配"

    def test_determinize_preserves_public_tribute_card_owner(self):
        state = _make_test_state()
        tribute = state.hands[3][0]
        returned = state.hands[0][0]
        state.hands[3].remove(tribute)
        state.hands[0].append(tribute)
        state.history.append(TributeSent(3, 0, tribute, reason="single"))
        state.hands[0].remove(returned)
        state.hands[3].append(returned)
        state.history.append(TributeReturned(0, 3, returned, reason="single"))

        new_state = determinize(state, player=1, rng=random.Random(99))

        assert tribute in new_state.hands[0]
        assert returned in new_state.hands[3]

    def test_determinize_releases_known_tribute_card_after_it_is_played(self):
        state = _make_test_state()
        tribute = state.hands[3][0]
        state.hands[3].remove(tribute)
        state.hands[0].append(tribute)
        state.history.append(TributeSent(3, 0, tribute, reason="single"))
        state.hands[0].remove(tribute)
        state.history.append(
            TurnPlayed(
                player=0,
                pattern=Pattern(PatternType.SINGLE, tribute.rank, 1, (tribute,)),
                hand_remaining=len(state.hands[0]),
            )
        )

        new_state = determinize(state, player=1, rng=random.Random(99))

        assert len(new_state.hands[0]) == len(state.hands[0])

    def test_determinize_does_not_read_opponents_real_hidden_cards(self):
        state_a = _make_test_state()
        state_b = copy.deepcopy(state_a)
        state_b.hands[1], state_b.hands[2] = state_b.hands[2], state_b.hands[1]

        sampled_a = determinize(state_a, player=0, rng=random.Random(1234))
        sampled_b = determinize(state_b, player=0, rng=random.Random(1234))

        assert sampled_a.hands == sampled_b.hands

    def test_opponent_pass_is_soft_evidence_against_higher_single(self):
        top = Pattern(PatternType.SINGLE, 8, 1, (Card(8, Suit.HEARTS),))
        evidence = (PassEvidence(player=2, top_player=1, pattern=top),)

        low = card_owner_likelihood(
            Card(5, Suit.CLUBS),
            owner=2,
            evidence=evidence,
            level=2,
        )
        high = card_owner_likelihood(
            Card(14, Suit.CLUBS),
            owner=2,
            evidence=evidence,
            level=2,
        )

        assert 0 < high < low


class TestUCB1:
    """测试 UCB1 计算。"""

    def test_ucb1_unvisited_node(self):
        """未访问节点返回 inf。"""
        state = _make_test_state()
        node = MCTSNode(state=state, player=0)
        node.visits = 0

        score = ucb1_score(node, parent_visits=10, c=1.41)
        assert score == float('inf')

    def test_ucb1_exploration_bonus(self):
        """访问少的节点有探索奖励。"""
        state = _make_test_state()

        node1 = MCTSNode(state=state, player=0)
        node1.visits = 1
        node1.wins = 0.5

        node2 = MCTSNode(state=state, player=0)
        node2.visits = 10
        node2.wins = 5.0

        # 两个节点胜率相同，但 node1 访问少，应该有更高的探索奖励
        score1 = ucb1_score(node1, parent_visits=100, c=1.41)
        score2 = ucb1_score(node2, parent_visits=100, c=1.41)

        assert score1 > score2


class TestMCTSSearch:
    """测试 MCTS 搜索。"""

    def test_mcts_search_runs(self):
        """MCTS 搜索能正常运行。"""
        state = _make_test_state()
        root = MCTSNode(state=state, player=0)

        best_child = mcts_search(
            root=root,
            iterations=10,  # 少量迭代，快速测试
            ucb_c=1.41,
            max_actions=3,
            rollout_strategy=1,
        )

        # 应该返回一个子节点
        assert best_child is None or isinstance(best_child, MCTSNode)

    def test_mcts_search_updates_visits(self):
        """MCTS 搜索正确更新访问次数。"""
        state = _make_test_state()
        root = MCTSNode(state=state, player=0)

        iterations = 20
        mcts_search(
            root=root,
            iterations=iterations,
            ucb_c=1.41,
            max_actions=3,
            rollout_strategy=1,
        )

        # 根节点应该被访问了 iterations 次
        assert root.visits == iterations

    def test_legal_actions_keep_finish_beyond_top_n(self):
        """MCTS 剪枝不能漏掉可一手出完的终局动作。"""
        state = _make_test_state()
        state.wild_card = None
        state.table = [Pattern(PatternType.SINGLE, 8, 1, (Card(8, Suit.HEARTS),), 0)]
        state.hands[0] = [
            Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER),
            Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER),
            Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
            Card(RANK_BIG_JOKER, Suit.BIG_JOKER),
        ]

        actions = _get_legal_actions(state, player=0, max_actions=1)

        assert actions[-1] is not None
        assert actions[-1].type == PatternType.FOUR_JOKERS
        assert len(actions[-1].cards) == len(state.hands[0])

    def test_information_set_search_samples_each_simulation(self, monkeypatch):
        state = _make_test_state()
        calls = {"count": 0}

        from guandan.ai.mcts import information_set as module

        real_determinize = module.determinize

        def counted_determinize(*args, **kwargs):
            calls["count"] += 1
            return real_determinize(*args, **kwargs)

        monkeypatch.setattr(module, "determinize", counted_determinize)
        result = information_set_search(
            state,
            player=0,
            rng=random.Random(7),
            iterations=4,
            max_actions=3,
            max_tree_depth=2,
            rollout_strategy=1,
            rollout_max_turns=2,
        )

        assert result.simulations == 4
        assert result.sampled_worlds == 4
        assert calls["count"] == 4
        assert result.actions
        assert all(action.availability >= action.visits for action in result.actions)

    def test_team_selection_reverses_value_for_opponent_nodes(self):
        strong_for_root = InformationSetNode(
            visits=10,
            value_sum=8.0,
            availability=20,
            prior=0.0,
        )
        weak_for_root = InformationSetNode(
            visits=10,
            value_sum=2.0,
            availability=20,
            prior=0.0,
        )

        own_strong = team_selection_score(
            strong_for_root,
            node_visits=20,
            actor_team=0,
            root_team=0,
            exploration=0.0,
            prior_weight=0.0,
        )
        own_weak = team_selection_score(
            weak_for_root,
            node_visits=20,
            actor_team=0,
            root_team=0,
            exploration=0.0,
            prior_weight=0.0,
        )
        opponent_strong = team_selection_score(
            strong_for_root,
            node_visits=20,
            actor_team=1,
            root_team=0,
            exploration=0.0,
            prior_weight=0.0,
        )
        opponent_weak = team_selection_score(
            weak_for_root,
            node_visits=20,
            actor_team=1,
            root_team=0,
            exploration=0.0,
            prior_weight=0.0,
        )

        assert own_strong > own_weak
        assert opponent_weak > opponent_strong

    def test_unavailable_children_do_not_consume_widening_capacity(self):
        node = InformationSetNode(
            children={
                ("unavailable",): InformationSetNode(action_key=("unavailable",)),
            }
        )
        actions = {PASS_ACTION: None}

        assert _has_expansion_capacity(node, actions, widening_limit=1) is True

    def test_stratified_candidates_keep_structure_and_bomb(self):
        state = _make_test_state()
        state.wild_card = None
        state.table = []
        state.hands[0] = [
            Card(3, Suit.HEARTS),
            Card(4, Suit.DIAMONDS),
            Card(5, Suit.SPADES),
            Card(6, Suit.CLUBS),
            Card(7, Suit.HEARTS),
            Card(9, Suit.SPADES),
            Card(9, Suit.HEARTS),
            Card(9, Suit.CLUBS),
            Card(9, Suit.DIAMONDS),
            Card(14, Suit.CLUBS),
        ]

        candidates = enumerate_search_candidates(state, player=0, max_candidates=5)

        assert any(pattern.type == PatternType.STRAIGHT for pattern in candidates)
        assert any(pattern.type == PatternType.BOMB for pattern in candidates)


class TestMCTSEvaluation:
    """测试 rollout 结果评分。"""

    def test_finished_double_up_scores_best_for_root_team(self):
        state = _make_test_state()
        state.finished = True
        state.finish_order = [0, 2, 1]

        assert _evaluate_result(state, root_player=0) == pytest.approx(1.0)
        assert _evaluate_result(state, root_player=1) == pytest.approx(0.0)

    def test_finished_head_and_last_is_only_small_edge(self):
        state = _make_test_state()
        state.finished = True
        state.finish_order = [0, 1, 3]

        assert _evaluate_result(state, root_player=0) == pytest.approx(0.766666, rel=1e-4)
        assert _evaluate_result(state, root_player=1) == pytest.approx(0.233333, rel=1e-4)

    def test_unfinished_rollout_uses_hand_sizes(self):
        state = _make_test_state()
        state.hands = [
            [Card(3, Suit.HEARTS)],
            [Card(4, Suit.HEARTS)] * 8,
            [Card(5, Suit.HEARTS)],
            [Card(6, Suit.HEARTS)] * 8,
        ]

        assert _evaluate_result(state, root_player=0) > 0.5


class TestMCTSRolloutPolicy:
    """测试 MCTS rollout 的轻量策略。"""

    def test_rollout_uses_smallest_legal_pattern_without_full_strategy(self):
        state = _make_test_state()
        state.wild_card = None
        state.table = [Pattern(PatternType.SINGLE, 8, 1, (Card(8, Suit.HEARTS),), 0)]
        state.hands[1] = [Card(9, Suit.HEARTS), Card(14, Suit.HEARTS)]

        pattern = _rollout_select_pattern(state, 1, rollout_strategy_level=1)

        assert pattern is not None
        assert pattern.type == PatternType.SINGLE
        assert pattern.rank == 9

    def test_rollout_level_two_passes_when_teammate_leads(self):
        top = Pattern(PatternType.SINGLE, 8, 1, (Card(8, Suit.HEARTS),), 0)
        state = _make_test_state()
        state.table = [top]
        state.turn_index = 0
        state.hands[0] = [Card(9, Suit.HEARTS), Card(14, Suit.HEARTS)]

        from guandan.engine.events import TurnPlayed

        state.history.append(TurnPlayed(player=2, pattern=top, hand_remaining=1))

        assert _rollout_select_pattern(state, 0, rollout_strategy_level=2) is None

    def test_rollout_level_two_finishes_before_teammate_pass(self):
        top = Pattern(PatternType.SINGLE, 8, 1, (Card(8, Suit.HEARTS),), 0)
        state = _make_test_state()
        state.table = [top]
        state.turn_index = 0
        state.hands[0] = [Card(9, Suit.HEARTS)]

        from guandan.engine.events import TurnPlayed

        state.history.append(TurnPlayed(player=2, pattern=top, hand_remaining=1))

        pattern = _rollout_select_pattern(state, 0, rollout_strategy_level=2)

        assert pattern is not None
        assert pattern.type == PatternType.SINGLE
        assert pattern.rank == 9

    def test_rollout_does_not_reuse_single_wild_card(self):
        """rollout 快速枚举不能把 1 张逢人配当作 2 张牌使用。"""
        wild = Card(5, Suit.HEARTS)
        top = Pattern(PatternType.PAIR, 8, 1, (Card(8, Suit.HEARTS), Card(8, Suit.DIAMONDS)))
        state = _make_test_state(level=5)
        state.wild_card = wild
        state.table = [top]
        state.hands[1] = [Card(9, Suit.HEARTS), wild]

        pattern = _rollout_select_pattern(state, 1, rollout_strategy_level=1)

        assert pattern is not None
        assert pattern.type == PatternType.PAIR
        assert pattern.rank == 9
        assert pattern.cards.count(wild) == 1

    def test_rollout_sorts_single_cards_by_level_strength(self):
        """级牌单张应按实际强度排序，避免 rollout 先浪费级牌。"""
        state = _make_test_state(level=2)
        state.wild_card = Card(2, Suit.HEARTS)
        state.table = []
        state.hands[0] = [Card(2, Suit.SPADES), Card(9, Suit.CLUBS)]

        pattern = _rollout_select_pattern(state, 0, rollout_strategy_level=1)

        assert pattern is not None
        assert pattern.type == PatternType.SINGLE
        assert pattern.rank == 9


class TestProfessionalStrategy:
    """测试职业策略集成。"""

    def test_professional_strategy_select_pattern(self):
        """职业策略能返回有效牌型。"""
        state = _make_test_state()
        strategy = ProfessionalStrategy(iterations=10, rng=random.Random(42))

        pattern = strategy.select_pattern(state, player=0)

        # 应该返回 None 或有效牌型
        assert pattern is None or pattern.cards

    def test_professional_strategy_makes_legal_moves(self):
        """职业策略返回的牌型可以合法出牌。"""
        state = _make_test_state()
        player = 0
        strategy = ProfessionalStrategy(iterations=10, rng=random.Random(42))

        # 获取策略选择
        pattern = strategy.select_pattern(state, player)

        if pattern is not None:
            # 验证可以合法出牌
            from guandan.engine.state import IllegalPlayError
            try:
                play_pattern(state, player, pattern)
                # 如果没有抛异常，说明是合法出牌
                assert True
            except IllegalPlayError:
                pytest.fail(f"Strategy returned illegal pattern: {pattern}")

    def test_professional_strategy_attributes(self):
        """职业策略有正确的属性。"""
        strategy = ProfessionalStrategy()

        assert strategy.name == "职业"
        assert strategy.difficulty == 3

    def test_professional_default_parameters_follow_mcts_config(self):
        """职业策略默认参数应跟 MCTS_CONFIG 保持一致，避免配置失效。"""
        strategy = ProfessionalStrategy()

        assert strategy.iterations == MCTS_CONFIG["iterations"]
        assert strategy.max_actions == MCTS_CONFIG["top_actions"]
        assert strategy.rollout_strategy == MCTS_CONFIG["rollout_strategy"]
        assert strategy.mcts_hand_threshold == MCTS_CONFIG["hand_threshold"]
        assert strategy.rollout_max_turns == MCTS_CONFIG["rollout_max_turns"]

    def test_professional_finishes_with_complete_straight(self):
        """职业档应能识别顺子一手出完，不被候选 Top-N 漏掉。"""
        state = _make_test_state()
        state.wild_card = None
        state.table = []
        state.hands[0] = [
            Card(3, Suit.HEARTS),
            Card(4, Suit.DIAMONDS),
            Card(5, Suit.SPADES),
            Card(6, Suit.CLUBS),
            Card(7, Suit.HEARTS),
        ]
        strategy = ProfessionalStrategy(iterations=1, rng=random.Random(42))

        pattern = strategy.select_pattern(state, player=0)

        assert pattern is not None
        assert pattern.type == PatternType.STRAIGHT
        assert len(pattern.cards) == 5

    def test_professional_uses_fast_strategy_before_endgame(self, monkeypatch):
        """M6：前中期大手牌不跑 MCTS，避免单步过慢。"""
        state = _make_test_state()
        strategy = ProfessionalStrategy(iterations=10, rng=random.Random(42))

        def fail_mcts(*args, **kwargs):
            raise AssertionError("MCTS should not run before endgame")

        monkeypatch.setattr("guandan.ai.strategies.professional.mcts_search", fail_mcts)

        pattern = strategy.select_pattern(state, player=0)

        assert pattern is None or pattern.cards

    def test_professional_uses_mcts_in_endgame(self, monkeypatch):
        """M6：手牌进入阈值后仍启用 MCTS。"""
        state = _make_test_state()
        state.hands[0] = [
            Card(3, Suit.HEARTS),
            Card(3, Suit.DIAMONDS),
            Card(4, Suit.HEARTS),
            Card(5, Suit.DIAMONDS),
            Card(7, Suit.SPADES),
            Card(9, Suit.CLUBS),
            Card(11, Suit.HEARTS),
            Card(12, Suit.DIAMONDS),
            Card(13, Suit.SPADES),
            Card(14, Suit.CLUBS),
        ]
        strategy = ProfessionalStrategy(iterations=1, rng=random.Random(42))
        calls = {"count": 0}

        def fake_mcts(*args, **kwargs):
            calls["count"] += 1
            return None

        monkeypatch.setattr("guandan.ai.strategies.professional.mcts_search", fake_mcts)

        assert strategy.select_pattern(state, player=0) is None
        assert calls["count"] == 1

    def test_professional_mcts_gate_ignores_short_partner(self):
        """只有队友短手牌时不应误触发 MCTS，避免前中期额外等待。"""
        state = _make_test_state()
        state.hands[0] = [
            Card(3, Suit.HEARTS),
            Card(3, Suit.DIAMONDS),
            Card(4, Suit.HEARTS),
            Card(6, Suit.DIAMONDS),
            Card(9, Suit.SPADES),
            Card(13, Suit.CLUBS),
        ]
        state.hands[1] = [
            Card(4, Suit.DIAMONDS),
            Card(5, Suit.DIAMONDS),
            Card(6, Suit.SPADES),
            Card(7, Suit.CLUBS),
        ]
        state.hands[2] = [Card(5, Suit.CLUBS)]
        state.hands[3] = [
            Card(8, Suit.DIAMONDS),
            Card(9, Suit.DIAMONDS),
            Card(10, Suit.SPADES),
            Card(11, Suit.CLUBS),
        ]
        strategy = ProfessionalStrategy(mcts_hand_threshold=3)

        assert strategy._should_use_mcts(state, player=0) is False

    def test_professional_mcts_gate_uses_short_opponents(self):
        """对手短手牌仍是关键局面，应触发 MCTS。"""
        state = _make_test_state()
        state.hands[0] = [
            Card(3, Suit.HEARTS),
            Card(3, Suit.DIAMONDS),
            Card(4, Suit.HEARTS),
            Card(6, Suit.DIAMONDS),
            Card(9, Suit.SPADES),
            Card(13, Suit.CLUBS),
        ]
        state.hands[1] = [Card(4, Suit.DIAMONDS)]
        state.hands[2] = [
            Card(5, Suit.CLUBS),
            Card(6, Suit.CLUBS),
            Card(7, Suit.CLUBS),
            Card(8, Suit.CLUBS),
        ]
        state.hands[3] = [
            Card(8, Suit.DIAMONDS),
            Card(9, Suit.DIAMONDS),
            Card(10, Suit.SPADES),
            Card(11, Suit.CLUBS),
        ]
        strategy = ProfessionalStrategy(mcts_hand_threshold=3)

        assert strategy._should_use_mcts(state, player=0) is True

    @pytest.mark.parametrize("seed", [733, 947])
    def test_information_set_move_executes_in_real_reached_endgame(self, seed):
        from guandan.ai.play import play_or_pass
        from guandan.ai.strategy import make_strategy
        from guandan.engine.state import make_initial_state

        state = make_initial_state(seed=seed)
        bots = [make_strategy(0) for _ in range(4)]
        rng = random.Random(seed)
        while not state.finished and min(
            (state.hand_size(player) for player in range(4) if state.hand_size(player)),
            default=99,
        ) > 10:
            player = state.turn_index
            play_or_pass(state, player, bots[player], rng)

        player = state.turn_index
        strategy = ProfessionalStrategy(
            iterations=8,
            time_budget_ms=0,
            max_tree_depth=4,
            rollout_max_turns=8,
            rng=random.Random(seed),
        )
        pattern = strategy.select_pattern(state, player)

        if pattern is None:
            pass_turn(state, player)
        else:
            play_pattern(state, player, pattern)
        assert strategy.last_search is not None
        assert strategy.last_search.simulations == 8

    def test_fixed_iteration_search_is_seed_reproducible(self):
        state = _make_test_state(seed=777)
        first = information_set_search(
            state,
            player=0,
            rng=random.Random(99),
            iterations=6,
            max_actions=4,
            max_tree_depth=3,
            rollout_max_turns=5,
        )
        second = information_set_search(
            state,
            player=0,
            rng=random.Random(99),
            iterations=6,
            max_actions=4,
            max_tree_depth=3,
            rollout_max_turns=5,
        )

        assert first.pattern == second.pattern
        assert first.actions == second.actions

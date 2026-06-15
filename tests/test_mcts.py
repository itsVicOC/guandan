"""MCTS 模块测试。

测试：
1. 确定化逻辑正确性
2. UCB1 计算
3. MCTS 搜索循环
4. ProfessionalStrategy 集成
"""
from __future__ import annotations

import random

import pytest

from guandan.ai.mcts.determinize import _get_all_cards_in_game, determinize
from guandan.ai.mcts.node import MCTSNode
from guandan.ai.mcts.search import _evaluate_result, mcts_search, ucb1_score
from guandan.ai.strategies.professional import ProfessionalStrategy
from guandan.engine.card import RANK_BIG_JOKER, RANK_SMALL_JOKER, Card, Suit
from guandan.engine.deck import deal, make_deck, shuffle_deck
from guandan.engine.hand import PatternType
from guandan.engine.state import GameState, play_pattern


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

"""戴长胜策略测试。

测试：
1. Profile 加载
2. 风格化参数应用
3. 炸弹吝啬行为
4. 配合意识
5. 策略集成
"""
from __future__ import annotations

import random

import pytest

from guandan.ai.profiles import load_profile
from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
from guandan.engine.card import Card, Suit
from guandan.engine.deck import deal, make_deck, shuffle_deck
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.state import GameState


def _make_test_state(level: int = 2, seed: int = 42) -> GameState:
    """创建测试用游戏状态。"""
    rng = random.Random(seed)
    deck = make_deck()
    shuffle_deck(deck, rng)
    hands = deal(deck)

    # 找到逢人配
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


class TestProfileLoading:
    """测试 Profile 加载。"""

    def test_load_dachangsheng_profile(self):
        """加载戴长胜 profile。"""
        profile = load_profile("dachangsheng")

        assert profile["name"] == "戴长胜"
        assert profile["difficulty"] == 4
        assert "mcts" in profile
        assert "style" in profile

    def test_load_profile_without_extension(self):
        """加载时可以省略 .json 扩展名。"""
        profile = load_profile("dachangsheng")
        assert profile["name"] == "戴长胜"

    def test_load_nonexistent_profile(self):
        """加载不存在的 profile 抛异常。"""
        with pytest.raises(FileNotFoundError):
            load_profile("nonexistent")

    def test_profile_has_required_fields(self):
        """Profile 包含必需字段。"""
        profile = load_profile("dachangsheng")

        assert "name" in profile
        assert "difficulty" in profile
        assert "description" in profile
        assert "mcts" in profile
        assert "style" in profile

        # MCTS 配置
        mcts = profile["mcts"]
        assert "iterations" in mcts
        assert isinstance(mcts["iterations"], int)

        # Style 参数
        style = profile["style"]
        assert "bomb_threshold" in style
        assert "control_priority" in style
        assert "teammate_awareness" in style
        assert "drift_bonus" in style


class TestDaiChangshengStrategy:
    """测试戴长胜策略。"""

    def test_strategy_initialization(self):
        """策略初始化。"""
        strategy = DaiChangshengStrategy(rng=random.Random(42))

        assert strategy.name == "戴长胜"
        assert strategy.difficulty == 4
        assert strategy.style is not None
        assert "bomb_threshold" in strategy.style

    def test_strategy_select_pattern(self):
        """策略能返回有效牌型。"""
        state = _make_test_state()
        strategy = DaiChangshengStrategy(rng=random.Random(42))

        pattern = strategy.select_pattern(state, player=0)

        # 应该返回 None 或有效牌型
        assert pattern is None or pattern.cards

    def test_strategy_attributes(self):
        """策略有正确的属性。"""
        strategy = DaiChangshengStrategy()

        assert strategy.name == "戴长胜"
        assert strategy.difficulty == 4
        assert strategy.iterations >= 100  # 应该比档3多

    def test_strategy_uses_profile_iterations(self):
        """策略使用 profile 中的迭代次数。"""
        strategy = DaiChangshengStrategy()
        profile = load_profile("dachangsheng")

        assert strategy.iterations == profile["mcts"]["iterations"]


class TestStyleBehavior:
    """测试风格化行为。"""

    def test_is_bomb_detection(self):
        """正确识别炸弹牌型。"""
        strategy = DaiChangshengStrategy()

        # 创建炸弹
        bomb = Pattern(
            cards=[Card(5, s) for s in [Suit.SPADES, Suit.HEARTS, Suit.CLUBS, Suit.DIAMONDS]],
            type=PatternType.BOMB,
            rank=5,
            length=4,
        )
        assert strategy._is_bomb(bomb) is True

        # 创建非炸弹
        single = Pattern(cards=[Card(3, Suit.SPADES)], type=PatternType.SINGLE, rank=3, length=1)
        assert strategy._is_bomb(single) is False

    def test_teammate_first_detection(self):
        """正确判断队友是否头游。"""
        state = _make_test_state()
        strategy = DaiChangshengStrategy()

        # 初始状态，没有人头游
        assert strategy._teammate_is_first(state, player=0) is False

        # 模拟队友头游
        state.finish_order.append(2)  # player 2 是 player 0 的队友
        assert strategy._teammate_is_first(state, player=0) is True

    def test_opponent_min_cards(self):
        """正确获取对手最少手牌数。"""
        state = _make_test_state()
        strategy = DaiChangshengStrategy()

        min_cards = strategy._get_opponent_min_cards(state, player=0)
        # 对手是 player 1 和 3
        assert min_cards > 0
        assert min_cards <= 27  # 初始最多27张

    def test_drift_finish_prefers_level_bomb(self):
        """最后一手可漂牌时，优先选择 5 张以上级牌炸弹。"""
        state = _make_test_state(level=5)
        state.hands[0] = [
            Card(5, Suit.HEARTS),
            Card(5, Suit.HEARTS),
            Card(5, Suit.DIAMONDS),
            Card(5, Suit.SPADES),
            Card(5, Suit.CLUBS),
        ]
        state.turn_index = 0
        state.table = []

        strategy = DaiChangshengStrategy(rng=random.Random(1))
        strategy.style["drift_bonus"] = 1.0

        fallback = Pattern(PatternType.SINGLE, 5, 1, (state.hands[0][0],), 0)
        chosen = strategy._apply_style(state, 0, fallback)

        assert chosen is not None
        assert chosen.type == PatternType.BOMB
        assert chosen.length == 5
        assert all(card.rank == state.level for card in chosen.cards)

    def test_preserve_drift_bomb_before_final_hand(self):
        """非终局跟牌时，避免提前拆掉可漂的级牌炸弹材料。"""
        state = _make_test_state(level=5)
        state.hands[0] = [
            Card(5, Suit.HEARTS),
            Card(5, Suit.HEARTS),
            Card(5, Suit.DIAMONDS),
            Card(5, Suit.SPADES),
            Card(5, Suit.CLUBS),
            Card(9, Suit.CLUBS),
        ]
        state.hands[1] = [Card(3, Suit.CLUBS)] * 8
        state.hands[3] = [Card(4, Suit.CLUBS)] * 8
        state.turn_index = 0
        state.table = [Pattern(PatternType.SINGLE, 4, 1, (Card(4, Suit.SPADES),), 0)]

        strategy = DaiChangshengStrategy(rng=random.Random(1))
        strategy.style["drift_bonus"] = 1.0

        early_level_play = Pattern(PatternType.SINGLE, 5, 1, (state.hands[0][0],), 0)

        assert strategy._apply_style(state, 0, early_level_play) is None

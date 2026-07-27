"""戴长胜策略测试。

测试：
1. Profile 加载
2. 风格参数到搜索先验的映射
3. 策略集成
"""
from __future__ import annotations

import json
import random
from pathlib import Path

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

    def test_checked_in_profile_matches_holdout_selected_parameters(self):
        profile = load_profile("dachangsheng")
        report_path = (
            Path(__file__).parents[1] / "benchmarks" / "ai-v2-style-tuning.json"
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))

        assert {
            key: profile["style"][key]
            for key in (
                "bomb_threshold",
                "control_priority",
                "teammate_awareness",
            )
        } == report["selected_style"]
        holdout = report["production_holdout"]
        assert holdout["candidate_wins"] > holdout["games"] / 2


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
        assert strategy.iterations > 0
        assert strategy.mcts_hand_threshold > 0

    def test_strategy_uses_profile_iterations(self):
        """策略使用 profile 中的迭代次数。"""
        strategy = DaiChangshengStrategy()
        profile = load_profile("dachangsheng")

        assert strategy.iterations == profile["mcts"]["iterations"]
        assert strategy.max_actions == profile["mcts"]["top_actions"]
        assert strategy.mcts_hand_threshold == profile["mcts"]["hand_threshold"]
        assert strategy.rollout_max_turns == profile["mcts"]["rollout_max_turns"]
        assert strategy.pass_probability_multiplier == profile["style"]["pass_probability_multiplier"]

    def test_finish_bomb_not_blocked_when_teammate_already_first(self):
        """队友已头游时，能直接出完的炸弹仍应执行。"""
        state = _make_test_state(level=2)
        state.wild_card = None
        state.finish_order = [2]
        state.turn_index = 0
        state.table = []
        state.hands[0] = [
            Card(9, Suit.SPADES),
            Card(9, Suit.HEARTS),
            Card(9, Suit.CLUBS),
            Card(9, Suit.DIAMONDS),
        ]
        strategy = DaiChangshengStrategy(rng=random.Random(42))

        pattern = strategy.select_pattern(state, player=0)

        assert pattern is not None
        assert pattern.type == PatternType.BOMB
        assert pattern.length == 4

    def test_finish_card_not_blocked_by_teammate_awareness(self):
        """队友领先时，能直接出完的响应不应被配合意识改成过牌。"""
        state = _make_test_state(level=2)
        state.wild_card = None
        state.turn_index = 0
        state.leader = 2
        state.table = [Pattern(PatternType.SINGLE, 8, 1, (Card(8, Suit.HEARTS),), 0)]
        state.hands[0] = [Card(9, Suit.SPADES)]
        state.hands[1] = [Card(3, Suit.CLUBS), Card(4, Suit.CLUBS)]
        state.hands[2] = [Card(5, Suit.CLUBS), Card(6, Suit.CLUBS)]
        state.hands[3] = [Card(7, Suit.CLUBS), Card(10, Suit.CLUBS)]
        strategy = DaiChangshengStrategy(rng=random.Random(42))
        strategy.style["teammate_awareness"] = 1.0

        pattern = strategy.select_pattern(state, player=0)

        assert pattern is not None
        assert pattern.type == PatternType.SINGLE
        assert pattern.rank == 9

    def test_style_parameters_feed_search_priors(self):
        strategy = DaiChangshengStrategy(
            style_overrides={
                "bomb_threshold": 0.5,
                "control_priority": 0.7,
                "teammate_awareness": 0.9,
            }
        )

        search_style = strategy._search_style()

        assert search_style.bomb_willingness == pytest.approx(0.75)
        assert search_style.control_priority == pytest.approx(0.7)
        assert search_style.teammate_awareness == pytest.approx(0.9)

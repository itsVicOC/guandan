"""存储模块测试：序列化、Profile、Savegame、History。"""
from __future__ import annotations

import random
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from guandan.engine.card import Card, Suit
from guandan.engine.deck import deal, make_deck, shuffle_deck
from guandan.engine.events import GameOver, Pass, ShuffleDeal, TurnPlayed
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.rules.patterns import find_complete_pattern
from guandan.engine.state import GameState, pass_turn, play_pattern
from guandan.storage import (
    delete_savegame,
    deserialize_events,
    has_savegame,
    load_game,
    load_history_detail,
    load_history_list,
    load_profile,
    restore_game_state,
    save_game,
    save_history,
    save_profile,
    serialize_events,
    update_statistics,
)


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


class TestSerialization:
    """测试事件序列化/反序列化。"""

    def test_serialize_deserialize_shuffle_deal(self):
        """ShuffleDeal 事件往返。"""
        event = ShuffleDeal(
            level=2,
            wild_card=Card(2, Suit.HEARTS),
            hand_sizes=(27, 27, 27, 27),
            first_player=0,
            seed=42,
        )

        # 序列化
        events = [event]
        dicts = serialize_events(events)

        assert len(dicts) == 1
        assert dicts[0]["_type"] == "ShuffleDeal"
        assert dicts[0]["level"] == 2
        assert dicts[0]["seed"] == 42

        # 反序列化
        restored = deserialize_events(dicts)
        assert len(restored) == 1
        assert restored[0] == event

    def test_serialize_deserialize_turn_played(self):
        """TurnPlayed 事件往返（含 Pattern）。"""
        cards = (Card(3, Suit.SPADES),)
        pattern = Pattern(cards=cards, type=PatternType.SINGLE, rank=3, length=1)
        event = TurnPlayed(player=0, pattern=pattern, hand_remaining=26)

        dicts = serialize_events([event])
        restored = deserialize_events(dicts)

        assert len(restored) == 1
        assert isinstance(restored[0], TurnPlayed)
        assert restored[0].player == 0
        assert restored[0].pattern.cards == cards
        assert restored[0].hand_remaining == 26

    def test_serialize_deserialize_pass(self):
        """Pass 事件往返。"""
        event = Pass(player=1, hand_remaining=25)

        dicts = serialize_events([event])
        restored = deserialize_events(dicts)

        assert len(restored) == 1
        assert restored[0] == event

    def test_serialize_deserialize_game_over(self):
        """GameOver 事件往返（含 tuple）。"""
        event = GameOver(
            finish_order=(2, 0, 1, 3),
            team_levels=(3, 2),
            drift=False,
            guo_a=True,
        )

        dicts = serialize_events([event])
        restored = deserialize_events(dicts)

        assert len(restored) == 1
        assert restored[0] == event
        assert isinstance(restored[0].finish_order, tuple)
        assert isinstance(restored[0].team_levels, tuple)

    def test_serialize_multiple_events(self):
        """多个事件往返。"""
        events = [
            ShuffleDeal(
                level=2,
                wild_card=None,
                hand_sizes=(27, 27, 27, 27),
                first_player=0,
                seed=42,
            ),
            Pass(player=0, hand_remaining=27),
            Pass(player=1, hand_remaining=27),
        ]

        dicts = serialize_events(events)
        restored = deserialize_events(dicts)

        assert len(restored) == 3
        assert restored == events

    def test_deserialize_unknown_event_type(self):
        """反序列化未知事件类型抛异常。"""
        dicts = [{"_type": "UnknownEvent", "foo": "bar"}]

        with pytest.raises(ValueError, match="Unknown event type"):
            deserialize_events(dicts)


class TestProfile:
    """测试 Profile 管理。"""

    def test_load_profile_default(self):
        """不存在时加载默认配置。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.profile.get_profile_path") as mock:
                mock.return_value = Path(tmpdir) / "profile.json"

                profile = load_profile()

                assert profile["player_name"] == "玩家"
                assert profile["preferences"]["default_difficulty"] == 2
                assert profile["statistics"]["total_games"] == 0

    def test_save_and_load_profile(self):
        """保存并加载配置。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.profile.get_profile_path") as mock:
                mock.return_value = Path(tmpdir) / "profile.json"

                # 保存
                profile = load_profile()
                profile["player_name"] = "测试玩家"
                save_profile(profile)

                # 加载
                loaded = load_profile()
                assert loaded["player_name"] == "测试玩家"
                assert "created_at" in loaded
                assert "updated_at" in loaded

    def test_update_statistics_win(self):
        """更新统计（获胜）。"""
        profile = load_profile()

        # 玩家上游（rank 1）
        update_statistics(profile, player_rank=1, difficulty=2)

        assert profile["statistics"]["total_games"] == 1
        assert profile["statistics"]["wins"] == 1
        assert profile["statistics"]["losses"] == 0
        assert profile["statistics"]["win_rate"] == 1.0
        assert profile["statistics"]["by_difficulty"]["2"]["games"] == 1
        assert profile["statistics"]["by_difficulty"]["2"]["wins"] == 1

    def test_update_statistics_loss(self):
        """更新统计（失败）。"""
        profile = load_profile()

        # 玩家下游（rank 4）
        update_statistics(profile, player_rank=4, difficulty=2)

        assert profile["statistics"]["total_games"] == 1
        assert profile["statistics"]["wins"] == 0
        assert profile["statistics"]["losses"] == 1
        assert profile["statistics"]["win_rate"] == 0.0

    def test_update_statistics_multiple_games(self):
        """更新统计（多局）。"""
        profile = load_profile()

        update_statistics(profile, player_rank=1, difficulty=2)  # 赢
        update_statistics(profile, player_rank=3, difficulty=2)  # 输
        update_statistics(profile, player_rank=2, difficulty=3)  # 赢

        assert profile["statistics"]["total_games"] == 3
        assert profile["statistics"]["wins"] == 2
        assert profile["statistics"]["losses"] == 1
        assert profile["statistics"]["win_rate"] == 2 / 3
        assert profile["statistics"]["by_difficulty"]["2"]["games"] == 2
        assert profile["statistics"]["by_difficulty"]["2"]["wins"] == 1
        assert profile["statistics"]["by_difficulty"]["3"]["games"] == 1
        assert profile["statistics"]["by_difficulty"]["3"]["wins"] == 1


class TestSavegame:
    """测试 Savegame 管理。"""

    def test_save_and_load_game(self):
        """保存并加载游戏。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.savegame.get_savegame_path") as mock:
                mock.return_value = Path(tmpdir) / "savegame.json"

                # 创建状态
                state = _make_test_state()

                # state.history 应该有 ShuffleDeal 事件
                # 需要手动添加
                from guandan.engine.events import ShuffleDeal
                shuffle_event = ShuffleDeal(
                    level=state.level,
                    wild_card=state.wild_card,
                    hand_sizes=tuple(len(h) for h in state.hands),
                    first_player=0,
                    seed=42,
                )
                state.history.append(shuffle_event)

                # 保存
                save_game(
                    state=state,
                    game_id="test_game_001",
                    player_seat=0,
                    ai_difficulties=[None, 2, 2, 2],
                    seed=42,
                )

                # 加载
                loaded = load_game()
                assert loaded is not None
                assert loaded["game_id"] == "test_game_001"
                assert loaded["metadata"]["player_seat"] == 0
                assert loaded["metadata"]["seed"] == 42
                assert isinstance(loaded["events"], list)
                assert len(loaded["events"]) > 0
                assert "state" in loaded

    def test_restore_game_state_from_snapshot(self):
        """从新存档快照恢复可继续游玩的 GameState。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.savegame.get_savegame_path") as mock:
                mock.return_value = Path(tmpdir) / "savegame.json"

                state = _make_test_state()
                shuffle_event = ShuffleDeal(
                    level=state.level,
                    wild_card=state.wild_card,
                    hand_sizes=tuple(len(h) for h in state.hands),
                    first_player=0,
                    seed=42,
                )
                state.history.append(shuffle_event)

                first_card = state.hands[0][0]
                pattern = find_complete_pattern([first_card], state.wild_card)
                assert pattern is not None
                play_pattern(state, 0, pattern)
                pass_turn(state, 1)

                save_game(state, "test", 0, [None, 2, 2, 2], 42)
                loaded = load_game()
                restored = restore_game_state(loaded)

                assert restored.level == state.level
                assert restored.wild_card == state.wild_card
                assert restored.hands == state.hands
                assert restored.turn_index == state.turn_index
                assert restored.table == state.table
                assert restored.passed_players == state.passed_players
                assert restored.history == state.history

    def test_load_game_no_savegame(self):
        """无存档时返回 None。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.savegame.get_savegame_path") as mock:
                mock.return_value = Path(tmpdir) / "savegame.json"

                loaded = load_game()
                assert loaded is None

    def test_has_savegame(self):
        """检查是否存在存档。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.savegame.get_savegame_path") as mock:
                mock.return_value = Path(tmpdir) / "savegame.json"

                assert has_savegame() is False

                # 保存
                state = _make_test_state()
                save_game(state, "test", 0, [None, 2, 2, 2], 42)

                assert has_savegame() is True

    def test_delete_savegame(self):
        """删除存档。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.savegame.get_savegame_path") as mock:
                mock.return_value = Path(tmpdir) / "savegame.json"

                # 保存
                state = _make_test_state()
                save_game(state, "test", 0, [None, 2, 2, 2], 42)
                assert has_savegame() is True

                # 删除
                delete_savegame()
                assert has_savegame() is False


class TestHistory:
    """测试 History 管理。"""

    def test_save_and_load_history(self):
        """保存并加载历史记录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.history.get_history_dir") as mock:
                mock.return_value = Path(tmpdir)

                # 创建状态（含 GameOver 事件）
                state = _make_test_state()
                game_over = GameOver(
                    finish_order=(2, 0, 1, 3),
                    team_levels=(3, 2),
                    drift=False,
                    guo_a=False,
                )
                state.history.append(game_over)

                # 保存
                save_history(
                    state=state,
                    game_id="game001",
                    player_seat=0,
                    ai_difficulties=[None, 2, 2, 2],
                    seed=42,
                    duration_seconds=180,
                )

                # 加载列表
                history_list = load_history_list()
                assert len(history_list) == 1
                assert history_list[0]["game_id"] == "game001"
                assert history_list[0]["result"]["player_rank"] == 2  # 0 在 finish_order 中排第 2
                assert history_list[0]["duration_seconds"] == 180

                # 加载详情
                detail = load_history_detail("game001")
                assert detail is not None
                assert detail["game_id"] == "game001"
                assert isinstance(detail["events"], list)
                assert len(detail["events"]) > 0

    def test_save_history_no_game_over(self):
        """保存没有 GameOver 事件的历史抛异常。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.history.get_history_dir") as mock:
                mock.return_value = Path(tmpdir)

                state = _make_test_state()

                with pytest.raises(ValueError, match="No GameOver event"):
                    save_history(state, "game001", 0, [None, 2, 2, 2], 42, 180)

    def test_load_history_list_empty(self):
        """无历史记录时返回空列表。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.history.get_history_dir") as mock:
                mock.return_value = Path(tmpdir)

                history_list = load_history_list()
                assert history_list == []

    def test_load_history_list_limit(self):
        """加载历史记录限制数量。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.history.get_history_dir") as mock:
                mock.return_value = Path(tmpdir)

                # 保存 3 条记录
                for i in range(3):
                    state = _make_test_state()
                    game_over = GameOver(
                        finish_order=(2, 0, 1, 3),
                        team_levels=(3, 2),
                        drift=False,
                        guo_a=False,
                    )
                    state.history.append(game_over)
                    save_history(state, f"game{i:03d}", 0, [None, 2, 2, 2], 42, 180)

                # 加载 2 条
                history_list = load_history_list(limit=2)
                assert len(history_list) == 2

    def test_load_history_detail_not_found(self):
        """加载不存在的历史记录返回 None。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.history.get_history_dir") as mock:
                mock.return_value = Path(tmpdir)

                detail = load_history_detail("nonexistent")
                assert detail is None

"""存储模块测试：序列化、Profile、Savegame、History。"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from guandan.engine.card import Card, Suit
from guandan.engine.deck import deal, make_deck, shuffle_deck
from guandan.engine.events import (
    Claim,
    GameOver,
    Pass,
    ShuffleDeal,
    TributeResisted,
    TributeReturned,
    TributeSent,
    TurnPlayed,
)
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.rules.patterns import find_complete_pattern
from guandan.engine.state import GameState, make_initial_state, pass_turn, play_pattern
from guandan.storage import (
    DEFAULT_PROFILE,
    delete_savegame,
    deserialize_events,
    has_savegame,
    load_game,
    load_history_detail,
    load_history_list,
    load_profile,
    record_match_statistics,
    record_round_statistics,
    restore_game_state,
    save_game,
    save_history,
    save_profile,
    serialize_events,
    update_profile,
    update_statistics,
)


def _make_test_state(level: int = 2, seed: int = 42) -> GameState:
    """创建测试用游戏状态。"""
    rng = random.Random(seed)
    deck = make_deck()
    shuffled = shuffle_deck(deck, rng)
    hands = deal(shuffled)

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
        leader=0,
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
            winner_team=0,
        )

        dicts = serialize_events([event])
        restored = deserialize_events(dicts)

        assert len(restored) == 1
        assert restored[0] == event
        assert isinstance(restored[0].finish_order, tuple)
        assert isinstance(restored[0].team_levels, tuple)
        assert restored[0].winner_team == 0

    def test_serialize_multiple_events(self):
        """多个事件往返。"""
        events = [
            ShuffleDeal(
                level=2,
                wild_card=None,
                hand_sizes=(27, 27, 27, 27),
                first_player=0,
                seed=42,
                team_levels=(2, 5),
            ),
            Pass(player=0, hand_remaining=27),
            Pass(player=1, hand_remaining=27),
        ]

        dicts = serialize_events(events)
        restored = deserialize_events(dicts)

        assert len(restored) == 3
        assert restored == events
        assert isinstance(restored[0], ShuffleDeal)
        assert restored[0].team_levels == (2, 5)

    def test_deserialize_unknown_event_type(self):
        """反序列化未知事件类型抛异常。"""
        dicts = [{"_type": "UnknownEvent", "foo": "bar"}]

        with pytest.raises(ValueError, match="Unknown event type"):
            deserialize_events(dicts)

    @pytest.mark.parametrize(
        "payload",
        [
            [{}],
            [{"_type": "Pass"}],
            [{"_type": "event_to_dict"}],
            ["not-an-object"],
        ],
    )
    def test_deserialize_rejects_malformed_event_payloads(self, payload):
        with pytest.raises(ValueError):
            deserialize_events(payload)


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
                assert profile["statistics"]["total_rounds"] == 0
                assert profile["statistics"]["total_matches"] == 0

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

    def test_load_profile_migrates_legacy_statistics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile.json"
            path.write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "player_name": "旧玩家",
                        "statistics": {
                            "total_games": 2,
                            "wins": 1,
                            "losses": 1,
                            "win_rate": 0.5,
                            "by_difficulty": {"2": {"games": 2, "wins": 1}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch("guandan.storage.profile.get_profile_path", return_value=path):
                profile = load_profile()

            assert profile["version"] == "3.0"
            assert profile["player_name"] == "旧玩家"
            assert profile["statistics"]["total_rounds"] == 2
            assert profile["statistics"]["head_rounds"] == 1
            assert profile["statistics"]["total_matches"] == 0
            assert profile["statistics"]["recorded_game_ids"] == []
            assert profile["statistics"]["by_difficulty_rounds"]["2"] == {
                "rounds": 2,
                "heads": 1,
            }
            assert profile["statistics"]["by_difficulty"] == {}

    def test_update_statistics_win(self):
        """更新统计（获胜）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.profile.get_profile_path") as mock:
                mock.return_value = Path(tmpdir) / "profile.json"
                profile = load_profile()

                update_statistics(profile, won=True, difficulty=2)

                assert profile["statistics"]["total_rounds"] == 1
                assert profile["statistics"]["head_rounds"] == 1
                assert profile["statistics"]["head_rate"] == 1.0
                assert profile["statistics"]["by_difficulty_rounds"]["2"]["rounds"] == 1
                assert profile["statistics"]["by_difficulty_rounds"]["2"]["heads"] == 1

    def test_update_statistics_loss(self):
        """更新统计（失败）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.profile.get_profile_path") as mock:
                mock.return_value = Path(tmpdir) / "profile.json"
                profile = load_profile()

                update_statistics(profile, won=False, difficulty=2)

                assert profile["statistics"]["total_rounds"] == 1
                assert profile["statistics"]["head_rounds"] == 0
                assert profile["statistics"]["head_rate"] == 0.0

    def test_update_statistics_multiple_games(self):
        """更新统计（多局）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.profile.get_profile_path") as mock:
                mock.return_value = Path(tmpdir) / "profile.json"
                profile = load_profile()

                update_statistics(profile, won=True, difficulty=2)
                update_statistics(profile, won=False, difficulty=2)
                update_statistics(profile, won=True, difficulty=3)

                assert profile["statistics"]["total_rounds"] == 3
                assert profile["statistics"]["head_rounds"] == 2
                assert profile["statistics"]["head_rate"] == 2 / 3
                assert profile["statistics"]["by_difficulty_rounds"]["2"] == {
                    "rounds": 2,
                    "heads": 1,
                }
                assert profile["statistics"]["by_difficulty_rounds"]["3"] == {
                    "rounds": 1,
                    "heads": 1,
                }

    def test_round_and_match_statistics_are_distinct_and_idempotent(self):
        profile = deepcopy(DEFAULT_PROFILE)

        assert record_round_statistics(
            profile, got_head=False, difficulty=2, game_id="round-1"
        )
        assert not record_round_statistics(
            profile, got_head=True, difficulty=2, game_id="round-1"
        )
        assert profile["statistics"]["total_matches"] == 0

        assert record_match_statistics(
            profile, won=True, difficulty=2, match_id="match-1"
        )
        assert not record_match_statistics(
            profile, won=False, difficulty=2, match_id="match-1"
        )
        assert profile["statistics"]["total_rounds"] == 1
        assert profile["statistics"]["total_matches"] == 1
        assert profile["statistics"]["match_wins"] == 1

    def test_update_profile_serializes_cross_process_writers(self, tmp_path: Path):
        path = tmp_path / "profile.json"
        with patch("guandan.storage.profile.get_profile_path", return_value=path):
            save_profile(deepcopy(DEFAULT_PROFILE))

        script = """
import sys
import time
from pathlib import Path
import guandan.storage.profile as profile_module

path = Path(sys.argv[1])
profile_module.get_profile_path = lambda: path

def mutate(profile):
    current = profile["preferences"]["default_difficulty"]
    time.sleep(0.25)
    profile["preferences"]["default_difficulty"] = current + 1

profile_module.update_profile(mutate)
"""
        env = dict(os.environ)
        source = str(Path(__file__).parents[1] / "src")
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (source, env.get("PYTHONPATH", "")) if part
        )
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(path)],
                cwd=Path(__file__).parents[1],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        failures = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=10)
            if process.returncode != 0:
                failures.append(f"stdout={stdout}\nstderr={stderr}")
        assert not failures, "\n".join(failures)

        with patch("guandan.storage.profile.get_profile_path", return_value=path):
            profile = load_profile()
        assert profile["preferences"]["default_difficulty"] == 4

    def test_update_profile_persists_mutator_result(self, tmp_path: Path):
        path = tmp_path / "profile.json"

        def rename(profile):
            profile["player_name"] = "并发玩家"
            return "updated"

        with patch("guandan.storage.profile.get_profile_path", return_value=path):
            assert update_profile(rename) == "updated"
            assert load_profile()["player_name"] == "并发玩家"

    def test_load_profile_propagates_io_errors(self, tmp_path: Path):
        path = tmp_path / "profile.json"
        path.write_text("{}", encoding="utf-8")
        with patch("guandan.storage.profile.get_profile_path", return_value=path), patch(
            "guandan.storage.profile.open", side_effect=PermissionError("denied")
        ), pytest.raises(PermissionError, match="denied"):
            load_profile()


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
                    team_levels=(2, 2),
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
                state.team_levels = [2, 5]
                shuffle_event = ShuffleDeal(
                    level=state.level,
                    wild_card=state.wild_card,
                    hand_sizes=tuple(len(h) for h in state.hands),
                    first_player=0,
                    seed=42,
                    team_levels=(2, 5),
                )
                state.history.append(shuffle_event)

                first_card = state.hands[0][0]
                pattern = find_complete_pattern([first_card], state.wild_card)
                assert pattern is not None
                play_pattern(state, 0, pattern)
                pass_turn(state, 3)

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
                assert restored.team_levels == [2, 5]
                assert restored.team_levels_final is None
                assert restored.match_finished is False
                assert restored.winner_team is None

    def test_restore_game_state_replays_tribute_events_without_snapshot(self):
        state = make_initial_state(level=5, first_player=0, seed=42)
        original_hands = [list(hand) for hand in state.hands]
        tribute = state.hands[3][0]
        returned = state.hands[0][0]
        state.hands[3].remove(tribute)
        state.hands[0].append(tribute)
        state.history.append(TributeSent(3, 0, tribute, reason="single"))
        state.hands[0].remove(returned)
        state.hands[3].append(returned)
        state.history.append(TributeReturned(0, 3, returned, reason="single"))

        restored = restore_game_state({"events": state.history})

        assert restored.hands == state.hands
        assert restored.history == state.history
        assert restored.hands != original_hands

    def test_load_game_migrates_legacy_snapshotless_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "savegame.json"
            state = make_initial_state(level=2, first_player=0, seed=42)
            # Write a real legacy payload using the current serializer, then remove
            # the full snapshot to exercise the events-only migration path.
            with patch("guandan.storage.savegame.get_savegame_path", return_value=path):
                save_game(state, "legacy", 0, [None, 2, 2, 2], 42)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["version"] = "1.0"
            payload.pop("state")
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch("guandan.storage.savegame.get_savegame_path", return_value=path):
                loaded = load_game()

            assert loaded is not None
            assert loaded["version"] == "3.0"
            assert loaded["match_id"] == "legacy"
            assert loaded["round_index"] == 1
            assert loaded["elapsed_seconds"] == 0
            assert "state" in loaded

    def test_load_game_migrates_version_2_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "savegame.json"
            state = make_initial_state(level=2, first_player=0, seed=42)
            with patch("guandan.storage.savegame.get_savegame_path", return_value=path):
                save_game(state, "legacy-v2", 0, [None, 2, 2, 2], 42)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["version"] = "2.0"
            for key in ("match_id", "round_index", "elapsed_seconds"):
                payload.pop(key)
                payload["metadata"].pop(key)
            path.write_text(json.dumps(payload), encoding="utf-8")

            with patch("guandan.storage.savegame.get_savegame_path", return_value=path):
                loaded = load_game()

            assert loaded is not None
            assert loaded["version"] == "3.0"
            assert loaded["match_id"] == "legacy-v2"

    def test_load_game_no_savegame(self):
        """无存档时返回 None。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.savegame.get_savegame_path") as mock:
                mock.return_value = Path(tmpdir) / "savegame.json"

                loaded = load_game()
                assert loaded is None

    def test_load_game_propagates_io_errors(self, tmp_path: Path):
        path = tmp_path / "savegame.json"
        path.write_text("{}", encoding="utf-8")
        with patch("guandan.storage.savegame.get_savegame_path", return_value=path), patch(
            "guandan.storage.savegame.open", side_effect=PermissionError("denied")
        ), pytest.raises(PermissionError, match="denied"):
            load_game()

    @pytest.mark.parametrize(
        "payload",
        [
            [],
            {},
            {"events": [{}]},
            {"events": "not-a-list"},
        ],
    )
    def test_load_game_returns_none_for_structurally_invalid_json(self, payload):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "savegame.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch("guandan.storage.savegame.get_savegame_path", return_value=path):
                assert load_game() is None

    def test_restore_game_state_normalizes_invalid_snapshot_error(self):
        with pytest.raises(ValueError, match="invalid savegame state"):
            restore_game_state({"state": {"level": 2}, "events": []})

    def test_load_game_rejects_snapshot_that_disagrees_with_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "savegame.json"
            state = make_initial_state(level=2, first_player=0, seed=42)
            with patch("guandan.storage.savegame.get_savegame_path", return_value=path):
                save_game(state, "consistent", 0, [None, 2, 2, 2], 42)
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["state"]["hands"][0].pop()
                path.write_text(json.dumps(payload), encoding="utf-8")

                assert load_game() is None

    def test_save_game_rejects_unsafe_game_id(self):
        state = make_initial_state(level=2, first_player=0, seed=42)

        with pytest.raises(ValueError, match="game_id"):
            save_game(state, "../../../escaped", 0, [None, 2, 2, 2], 42)

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

    def test_delete_savegame_only_removes_expected_round(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "savegame.json"
            state = make_initial_state(level=2, first_player=0, seed=42)
            with patch("guandan.storage.savegame.get_savegame_path", return_value=path):
                save_game(state, "current-round", 0, [None, 2, 2, 2], 42)
                assert delete_savegame(expected_game_id="other-round") is False
                assert path.exists()
                assert delete_savegame(expected_game_id="current-round") is True
                assert not path.exists()

    def test_savegame_persists_round_context_and_elapsed_time(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "savegame.json"
            state = make_initial_state(level=5, first_player=0, seed=42)
            with patch("guandan.storage.savegame.get_savegame_path", return_value=path):
                save_game(
                    state,
                    "round-3",
                    0,
                    [None, 2, 2, 2],
                    42,
                    match_id="match-7",
                    round_index=3,
                    elapsed_seconds=125,
                )
                loaded = load_game()

            assert loaded is not None
            assert loaded["match_id"] == "match-7"
            assert loaded["round_index"] == 3
            assert loaded["elapsed_seconds"] == 125
            assert loaded["metadata"]["elapsed_seconds"] == 125


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
                    winner_team=0,
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
                assert history_list[0]["match_id"] == "game001"
                assert history_list[0]["round_index"] == 1
                assert history_list[0]["result"]["player_rank"] == 2  # 0 在 finish_order 中排第 2
                assert history_list[0]["result"]["winner_team"] == 0
                assert history_list[0]["duration_seconds"] == 180

                # 加载详情
                detail = load_history_detail("game001")
                assert detail is not None
                assert detail["game_id"] == "game001"
                assert isinstance(detail["events"], list)
                assert len(detail["events"]) > 0

    def test_history_persists_action_statistics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.history.get_history_dir", return_value=Path(tmpdir)):
                state = _make_test_state()
                state.team_bomb_count = [2, 1]
                state.history.extend(
                    [
                        Pass(player=0, hand_remaining=27),
                        Claim(player=1, count=10),
                        TributeSent(3, 0, state.hands[3][0], reason="single"),
                        TributeResisted(player=2, team=0, reason="double"),
                        GameOver(
                            finish_order=(0, 1, 2, 3),
                            team_levels=(2, 2),
                            drift=False,
                            guo_a=False,
                        ),
                    ]
                )
                save_history(state, "stats-game", 0, [None, 2, 2, 2], 42, 10)
                detail = load_history_detail("stats-game")

            assert detail is not None
            assert detail["statistics"] == {
                "actions": 1,
                "plays": 0,
                "passes": 1,
                "claims": 1,
                "tributes": 1,
                "tribute_resisted": True,
                "bombs": [2, 1],
                "event_count": 5,
            }

    def test_save_history_no_game_over(self):
        """保存没有 GameOver 事件的历史抛异常。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.history.get_history_dir") as mock:
                mock.return_value = Path(tmpdir)

                state = _make_test_state()

                with pytest.raises(ValueError, match="No GameOver event"):
                    save_history(state, "game001", 0, [None, 2, 2, 2], 42, 180)

    def test_history_rejects_unsafe_game_id(self):
        state = _make_test_state()
        state.history.append(
            GameOver(
                finish_order=(0, 1, 2, 3),
                team_levels=(2, 2),
                drift=False,
                guo_a=False,
            )
        )

        with pytest.raises(ValueError, match="game_id"):
            save_history(state, "../../../escaped", 0, [None, 2, 2, 2], 42, 10)
        assert load_history_detail("../../../escaped") is None

    def test_save_history_is_idempotent_for_game_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("guandan.storage.history.get_history_dir", return_value=Path(tmpdir)):
                state = _make_test_state()
                state.history.append(
                    GameOver(
                        finish_order=(0, 1, 2, 3),
                        team_levels=(2, 2),
                        drift=False,
                        guo_a=False,
                    )
                )
                save_history(state, "same-game", 0, [None, 2, 2, 2], 42, 10)
                save_history(state, "same-game", 0, [None, 2, 2, 2], 42, 11)
                assert len(list(Path(tmpdir).glob("*_same-game.json"))) == 1

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

    def test_history_loaders_skip_structurally_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = Path(tmpdir)
            (history_dir / "2026-07-23_bad-list.json").write_text("[]", encoding="utf-8")
            (history_dir / "2026-07-23_bad-events.json").write_text(
                json.dumps({"events": [{}]}),
                encoding="utf-8",
            )
            with patch("guandan.storage.history.get_history_dir", return_value=history_dir):
                assert load_history_list() == []
                assert load_history_detail("bad-events") is None

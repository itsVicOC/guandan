# M5 实施计划：持久化系统

## 目标

实现完整的持久化系统，支持：
1. **用户配置（Profile）**：存储偏好、统计数据
2. **游戏存档（Savegame）**：断点续局
3. **历史战绩（History）**：对局记录和回放

## 背景分析

### 现有基础设施

**事件系统（已完成）**：
- `src/guandan/engine/events.py` 定义了所有事件类型
- 所有事件都是 frozen dataclass，完全可序列化
- `event_to_dict(ev)` 将事件转为 dict
- `state.history` 保存完整事件流
- ADR-0001 明确设计用于回放："回放本质就是事件序列"

**占位屏幕（已创建）**：
- `src/guandan/tui/screens/history.py` - 历史战绩屏（占位）
- `src/guandan/tui/screens/load_save.py` - 断点续局屏（占位）
- 都引用了 `~/.guandan/` 目录和 JSON 文件

**存储模块（空）**：
- `src/guandan/storage/__init__.py` 仅有一行注释

**已有 JSON 序列化模式**：
- `ai/profiles/__init__.py` 中的 `load_profile()` 函数
- 使用 `json.load()` 和 `pathlib.Path`
- 包内资源访问：`Path(__file__).parent / "profiles"`

### 缺失组件

1. **事件反序列化**：`dict_to_event()` 函数
2. **状态重建**：从事件流重建 GameState
3. **存储层**：文件读写、目录管理
4. **用户配置结构**：profile.json schema
5. **历史记录结构**：history.json schema
6. **存档结构**：savegame.json schema

## 设计决策

### 存储位置

```
~/.guandan/
├── profile.json      # 用户配置和统计
├── savegame.json     # 当前未完成的对局（单个）
└── history/          # 历史对局记录（多个）
    ├── 2026-06-05_143521_game001.json
    ├── 2026-06-05_144203_game002.json
    └── ...
```

**理由**：
- 用户目录是标准位置（`~/.app_name/`）
- history/ 子目录避免单文件过大
- 时间戳文件名便于排序和查找

### 数据格式

#### 1. Profile Schema

```json
{
  "version": "1.0",
  "player_name": "玩家",
  "preferences": {
    "default_difficulty": 2,
    "show_hints": true
  },
  "statistics": {
    "total_games": 10,
    "wins": 6,
    "losses": 4,
    "win_rate": 0.6,
    "by_difficulty": {
      "0": {"games": 2, "wins": 2},
      "1": {"games": 3, "wins": 2},
      "2": {"games": 5, "wins": 2}
    }
  },
  "created_at": "2026-06-05T14:30:00",
  "updated_at": "2026-06-05T15:45:00"
}
```

#### 2. Savegame Schema

```json
{
  "version": "1.0",
  "saved_at": "2026-06-05T14:35:21",
  "game_id": "game_2026-06-05_143521",
  "metadata": {
    "level": 2,
    "player_seat": 0,
    "ai_difficulties": [null, 2, 2, 2],
    "seed": 42
  },
  "events": [
    {"_type": "ShuffleDeal", "level": 2, "wild_card": {...}, ...},
    {"_type": "TurnPlayed", "player": 0, "pattern": {...}, ...},
    ...
  ],
  "current_state_snapshot": {
    "turn_index": 1,
    "finish_order": [],
    "hand_sizes": [20, 18, 19, 17]
  }
}
```

**设计要点**：
- `events` 是完整事件流，可重建状态
- `current_state_snapshot` 是优化（快速显示状态，不必回放）
- `metadata` 包含玩家座位和 AI 难度（不在事件流中）

#### 3. History Schema

每个历史记录文件：

```json
{
  "version": "1.0",
  "game_id": "game_2026-06-05_143521",
  "played_at": "2026-06-05T14:35:21",
  "duration_seconds": 180,
  "metadata": {
    "level": 2,
    "player_seat": 0,
    "ai_difficulties": [null, 2, 2, 2],
    "seed": 42
  },
  "result": {
    "finish_order": [2, 0, 1, 3],
    "final_levels": [3, 2],
    "drift": false,
    "guo_a": false,
    "player_rank": 2
  },
  "events": [
    ...完整事件流...
  ]
}
```

**设计要点**：
- 包含完整事件流（支持回放）
- `result` 提取关键结果（快速查询）
- `player_rank` 是玩家的名次（1-4）

## 实现方案

### 模块结构

```
src/guandan/storage/
├── __init__.py          # 导出公共 API
├── paths.py             # 路径管理（获取 ~/.guandan/）
├── serialization.py     # 事件序列化/反序列化
├── profile.py           # Profile 管理
├── savegame.py          # 存档管理
└── history.py           # 历史记录管理
```

### 核心实现

#### 1. paths.py - 路径管理

```python
from pathlib import Path

def get_storage_dir() -> Path:
    """获取存储目录 ~/.guandan/"""
    storage_dir = Path.home() / ".guandan"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir

def get_profile_path() -> Path:
    return get_storage_dir() / "profile.json"

def get_savegame_path() -> Path:
    return get_storage_dir() / "savegame.json"

def get_history_dir() -> Path:
    history_dir = get_storage_dir() / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir
```

#### 2. serialization.py - 事件序列化

```python
from typing import Any
from ..engine.events import Event, event_to_dict
from ..engine.card import Card, Suit
from ..engine.hand import Pattern, PatternType

def dict_to_event(d: dict[str, Any]) -> Event:
    """dict → Event（反序列化）"""
    from ..engine import events
    
    event_type = d.pop("_type")
    event_class = getattr(events, event_type)
    
    # 递归转换嵌套对象
    if event_type == "TurnPlayed":
        d["pattern"] = _dict_to_pattern(d["pattern"])
    elif event_type in ("TributeSent", "TributeReturned"):
        d["card"] = _dict_to_card(d["card"])
    elif event_type == "ShuffleDeal" and d.get("wild_card"):
        d["wild_card"] = _dict_to_card(d["wild_card"])
    
    return event_class(**d)

def _dict_to_card(d: dict) -> Card:
    """dict → Card"""
    return Card(rank=d["rank"], suit=Suit[d["suit"]])

def _dict_to_pattern(d: dict) -> Pattern:
    """dict → Pattern"""
    cards = [_dict_to_card(c) for c in d["cards"]]
    return Pattern(
        cards=tuple(cards),
        type=PatternType[d["type"]],
        rank=d["rank"],
        length=d["length"],
    )

def serialize_events(events: list[Event]) -> list[dict]:
    """事件流 → JSON 可序列化的 list[dict]"""
    return [event_to_dict(ev) for ev in events]

def deserialize_events(dicts: list[dict]) -> list[Event]:
    """list[dict] → 事件流"""
    return [dict_to_event(d.copy()) for d in dicts]
```

#### 3. profile.py - 用户配置

```python
import json
from datetime import datetime
from typing import Optional
from .paths import get_profile_path

DEFAULT_PROFILE = {
    "version": "1.0",
    "player_name": "玩家",
    "preferences": {
        "default_difficulty": 2,
        "show_hints": True,
    },
    "statistics": {
        "total_games": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "by_difficulty": {},
    },
    "created_at": None,
    "updated_at": None,
}

def load_profile() -> dict:
    """加载用户配置，不存在则返回默认值"""
    path = get_profile_path()
    if not path.exists():
        return DEFAULT_PROFILE.copy()
    
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_profile(profile: dict) -> None:
    """保存用户配置"""
    profile["updated_at"] = datetime.now().isoformat()
    if not profile.get("created_at"):
        profile["created_at"] = profile["updated_at"]
    
    path = get_profile_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)

def update_statistics(profile: dict, player_rank: int, difficulty: int) -> None:
    """更新统计数据（对局结束后调用）
    
    Args:
        profile: 用户配置
        player_rank: 玩家名次（1=上游，2=二游，3=三游，4=下游）
        difficulty: AI 难度（0-4）
    """
    stats = profile["statistics"]
    
    # 总对局数
    stats["total_games"] += 1
    
    # 胜负（上游/二游算赢，三游/下游算输）
    if player_rank <= 2:
        stats["wins"] += 1
    else:
        stats["losses"] += 1
    
    # 胜率
    stats["win_rate"] = stats["wins"] / stats["total_games"]
    
    # 分难度统计
    diff_key = str(difficulty)
    if diff_key not in stats["by_difficulty"]:
        stats["by_difficulty"][diff_key] = {"games": 0, "wins": 0}
    
    stats["by_difficulty"][diff_key]["games"] += 1
    if player_rank <= 2:
        stats["by_difficulty"][diff_key]["wins"] += 1
```

#### 4. savegame.py - 存档管理

```python
import json
from datetime import datetime
from typing import Optional
from .paths import get_savegame_path
from .serialization import serialize_events, deserialize_events
from ..engine.state import GameState
from ..engine.events import Event

def save_game(
    state: GameState,
    game_id: str,
    player_seat: int,
    ai_difficulties: list[Optional[int]],
    seed: int,
) -> None:
    """保存当前对局
    
    Args:
        state: 当前游戏状态
        game_id: 对局 ID
        player_seat: 玩家座位（0-3）
        ai_difficulties: 4 个座位的 AI 难度（玩家位置为 None）
        seed: 随机种子
    """
    data = {
        "version": "1.0",
        "saved_at": datetime.now().isoformat(),
        "game_id": game_id,
        "metadata": {
            "level": state.level,
            "player_seat": player_seat,
            "ai_difficulties": ai_difficulties,
            "seed": seed,
        },
        "events": serialize_events(state.history),
        "current_state_snapshot": {
            "turn_index": state.turn_index,
            "finish_order": list(state.finish_order),
            "hand_sizes": [len(h) for h in state.hands],
        },
    }
    
    path = get_savegame_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_game() -> Optional[dict]:
    """加载存档，返回 None 表示无存档"""
    path = get_savegame_path()
    if not path.exists():
        return None
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # 反序列化事件流
    data["events"] = deserialize_events(data["events"])
    
    return data

def delete_savegame() -> None:
    """删除存档（对局结束后调用）"""
    path = get_savegame_path()
    if path.exists():
        path.unlink()

def has_savegame() -> bool:
    """是否存在存档"""
    return get_savegame_path().exists()
```

#### 5. history.py - 历史记录

```python
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from .paths import get_history_dir
from .serialization import serialize_events, deserialize_events
from ..engine.state import GameState
from ..engine.events import Event, GameOver

def save_history(
    state: GameState,
    game_id: str,
    player_seat: int,
    ai_difficulties: list[Optional[int]],
    seed: int,
    duration_seconds: int,
) -> None:
    """保存历史记录（对局结束后调用）
    
    Args:
        state: 游戏状态
        game_id: 对局 ID
        player_seat: 玩家座位
        ai_difficulties: AI 难度列表
        seed: 随机种子
        duration_seconds: 对局时长（秒）
    """
    # 提取结果
    game_over_event = None
    for ev in reversed(state.history):
        if isinstance(ev, GameOver):
            game_over_event = ev
            break
    
    if not game_over_event:
        raise ValueError("No GameOver event found in history")
    
    # 玩家名次
    player_rank = game_over_event.finish_order.index(player_seat) + 1
    
    data = {
        "version": "1.0",
        "game_id": game_id,
        "played_at": datetime.now().isoformat(),
        "duration_seconds": duration_seconds,
        "metadata": {
            "level": state.level,
            "player_seat": player_seat,
            "ai_difficulties": ai_difficulties,
            "seed": seed,
        },
        "result": {
            "finish_order": list(game_over_event.finish_order),
            "final_levels": list(game_over_event.team_levels),
            "drift": game_over_event.drift,
            "guo_a": game_over_event.guo_a,
            "player_rank": player_rank,
        },
        "events": serialize_events(state.history),
    }
    
    # 文件名：时间戳_game_id.json
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"{timestamp}_{game_id}.json"
    path = get_history_dir() / filename
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_history_list() -> list[dict]:
    """加载历史记录列表（仅元数据，不含完整事件流）
    
    Returns:
        按时间倒序排列的历史记录列表
    """
    history_dir = get_history_dir()
    files = sorted(history_dir.glob("*.json"), reverse=True)
    
    result = []
    for file_path in files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # 只保留元数据，不加载完整事件流（节省内存）
        result.append({
            "game_id": data["game_id"],
            "played_at": data["played_at"],
            "duration_seconds": data["duration_seconds"],
            "result": data["result"],
            "metadata": data["metadata"],
            "file_path": str(file_path),
        })
    
    return result

def load_history_detail(game_id: str) -> Optional[dict]:
    """加载完整历史记录（含事件流，用于回放）"""
    history_dir = get_history_dir()
    
    # 查找匹配的文件（文件名包含 game_id）
    for file_path in history_dir.glob(f"*_{game_id}.json"):
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # 反序列化事件流
        data["events"] = deserialize_events(data["events"])
        
        return data
    
    return None
```

### TUI 集成

#### 更新 HistoryScreen

```python
from ..storage import load_history_list

class HistoryScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        history = load_history_list()
        
        if not history:
            with Center():
                with Vertical(id="hist-box"):
                    yield Static("📊 历史战绩", id="hist-title")
                    yield Static("暂无对局记录", id="hist-empty")
                    yield Button("← 返回", id="btn-back")
        else:
            with ScrollableContainer():
                yield Static("📊 历史战绩", id="hist-title")
                for entry in history[:20]:  # 最近 20 场
                    yield Static(self._format_entry(entry))
                yield Button("← 返回", id="btn-back")
        
        yield Footer()
    
    def _format_entry(self, entry: dict) -> str:
        """格式化历史记录条目"""
        played_at = entry["played_at"][:19]  # 去掉毫秒
        result = entry["result"]
        rank = result["player_rank"]
        rank_text = ["上游", "二游", "三游", "下游"][rank - 1]
        
        return f"{played_at} | {rank_text} | 难度{entry['metadata']['ai_difficulties'][1]}"
```

#### 更新 LoadSaveScreen

```python
from ..storage import load_game, has_savegame

class LoadSaveScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        
        if not has_savegame():
            with Center():
                with Vertical(id="load-box"):
                    yield Static("💾 断点续局", id="load-title")
                    yield Static("暂无存档", id="load-empty")
                    yield Button("← 返回", id="btn-back")
        else:
            savegame = load_game()
            with Center():
                with Vertical(id="load-box"):
                    yield Static("💾 断点续局", id="load-title")
                    yield Static(f"存档时间：{savegame['saved_at'][:19]}")
                    yield Static(f"级牌：{savegame['metadata']['level']}")
                    yield Static(f"已进行：{len(savegame['events'])} 步")
                    yield Button("继续游戏", id="btn-continue")
                    yield Button("删除存档", id="btn-delete")
                    yield Button("← 返回", id="btn-back")
        
        yield Footer()
```

#### 更新 GameScreen

在游戏结束时：
1. 调用 `save_history()` 保存历史
2. 调用 `update_statistics()` 更新统计
3. 调用 `delete_savegame()` 删除存档

在玩家退出时（未结束）：
1. 调用 `save_game()` 保存存档

## 实现步骤

### 步骤 1：实现存储基础设施
- `paths.py`：路径管理
- `serialization.py`：事件序列化/反序列化

### 步骤 2：实现持久化模块
- `profile.py`：用户配置
- `savegame.py`：存档
- `history.py`：历史记录

### 步骤 3：编写测试
- `tests/test_storage_serialization.py`：序列化测试
- `tests/test_storage_profile.py`：配置测试
- `tests/test_storage_savegame.py`：存档测试
- `tests/test_storage_history.py`：历史记录测试

### 步骤 4：集成到 TUI
- 更新 `HistoryScreen`
- 更新 `LoadSaveScreen`
- 更新 `GameScreen`（保存/加载逻辑）

### 步骤 5：更新文档
- README.md：M5 完成
- CHANGELOG.md：v0.6.0 条目

## 测试策略

### 单元测试

1. **序列化测试**：
   - 事件 → dict → 事件（往返）
   - 所有事件类型覆盖
   - 嵌套对象（Card、Pattern）

2. **Profile 测试**：
   - 加载/保存
   - 统计更新
   - 默认值

3. **Savegame 测试**：
   - 保存/加载游戏
   - 删除存档
   - 不存在存档

4. **History 测试**：
   - 保存历史
   - 加载列表
   - 加载详情

### 集成测试

1. **端到端测试**：
   - 完整对局 → 保存历史 → 加载历史
   - 中途退出 → 保存存档 → 加载存档 → 继续
   - 统计数据准确性

2. **文件系统测试**：
   - 目录创建
   - 文件权限
   - 并发访问（未来考虑）

## 验收标准

### 功能标准

- ✅ Profile 系统可用（加载/保存/统计）
- ✅ Savegame 系统可用（保存/加载/删除）
- ✅ History 系统可用（保存/列表/详情）
- ✅ TUI 屏幕功能完整（不再是占位）
- ✅ 事件序列化往返无损

### 质量标准

- ✅ 所有测试通过（172 既有 + 15+ 新增）
- ✅ JSON 格式正确（可读性好）
- ✅ 错误处理完善（文件不存在、格式错误）
- ✅ 目录自动创建

### 用户体验标准

- ✅ 历史屏显示最近 20 场对局
- ✅ 存档屏显示存档信息
- ✅ 对局结束后自动保存历史和统计
- ✅ 退出时提示保存存档

## 风险与缓解

### 风险 1：事件反序列化复杂

**问题**：嵌套对象（Card、Pattern）的反序列化容易出错

**缓解**：
- 充分的单元测试
- 所有事件类型覆盖
- 使用 dataclass.asdict/dataclass.replace

### 风险 2：文件损坏

**问题**：JSON 文件可能被用户手动修改导致损坏

**缓解**：
- Try-except 捕获 JSON 解析错误
- 验证 schema（version 字段）
- 提供错误提示和恢复机制

### 风险 3：磁盘空间

**问题**：历史记录文件可能占用大量空间

**缓解**：
- 只保存最近 N 场（如 100 场）
- 提供清理功能（未来）
- 压缩事件流（未来优化）

## 未来扩展

### M6+ 可能改进

1. **回放播放器**：
   - 步进/倒退
   - 速度控制
   - 暂停/继续

2. **统计分析**：
   - 胜率曲线
   - 分档位分析
   - AI 对比

3. **云同步**：
   - 多设备同步
   - 在线排行榜

4. **数据导出**：
   - 导出为 CSV
   - 导出为视频（截图序列）

## 总结

M5 通过 **事件序列化 + 文件存储** 实现完整持久化：
- Profile 系统：用户配置和统计
- Savegame 系统：断点续局
- History 系统：对局回放

架构清晰、易于扩展、用户体验完整。

# M4 实施计划：AI 档 4 戴长胜（风格化）

## 目标

实现档 4"戴长胜"AI，这是最高难度档位，具有独特的牌风：
- **炸弹吝啬**：不轻易出炸弹，保留控场能力
- **控场节奏**：掌握出牌节奏，控制局势
- **配合意识**：与队友高度配合
- **漂牌决策**：主动追求漂牌（最后一手出5张+级牌炸弹）

## 背景分析

### 现有 AI 档位（M3 完成）

- **档 0（新手）**：纯贪心 + 概率过牌
- **档 1（进阶）**：top-5 候选 + 估值排序
- **档 2（高手）**：估值 + 协作分 + 记牌
- **档 3（职业）**：IS-MCTS 搜索（迭代100次）

### 戴长胜风格特点

根据 README 的描述，戴长胜 AI 应该：
1. **炸弹吝啬**：更高的炸弹使用阈值，尽量保留到关键时刻
2. **控场节奏**：优先选择能控制局面的牌型，而不是简单的最小牌
3. **配合意识**：比档2更强的队友协作（让牌、接风意识）
4. **漂牌决策**：主动规划最后一手出5张+级牌炸弹

## 决策：M4 = M3 (IS-MCTS) + 风格化参数

### 核心设计

**M4 基于 M3 的 IS-MCTS**，通过调整参数和策略实现风格化：

1. **继承 ProfessionalStrategy**：不重新实现 MCTS，而是定制
2. **风格化参数**：通过 JSON 配置文件定义风格
3. **定制化评估**：修改 simulation 和 evaluation 函数
4. **更多迭代**：提升搜索质量（150-200 迭代）

### 风格化参数设计

创建 `src/guandan/ai/profiles/dachangsheng.json`：

```json
{
  "name": "戴长胜",
  "difficulty": 4,
  "description": "炸弹吝啬、控场节奏、配合意识、漂牌决策",
  "mcts": {
    "iterations": 150,
    "ucb_c": 1.41,
    "rollout_strategy": 2
  },
  "style": {
    "bomb_threshold": 0.8,
    "control_priority": 0.9,
    "teammate_awareness": 0.95,
    "drift_bonus": 0.7
  }
}
```

**参数说明**：
- `bomb_threshold` (0.8)：炸弹使用阈值，0.8表示只在80%必要时才用炸弹
- `control_priority` (0.9)：控场优先级，倾向选择能压制对手的牌
- `teammate_awareness` (0.95)：队友意识，更倾向让队友走
- `drift_bonus` (0.7)：漂牌奖励，追求5张+级牌炸弹的最后一手

### 实现方案

#### 方案 A：子类化（推荐）

```python
class DaiChangshengStrategy(ProfessionalStrategy):
    """戴长胜风格 AI：IS-MCTS + 风格化参数。"""
    
    name = "戴长胜"
    difficulty = 4
    
    def __init__(self, profile_path: str = None):
        # 加载 profile
        profile = self._load_profile(profile_path or "dachangsheng.json")
        
        # 初始化 MCTS（用 profile 的参数）
        super().__init__(
            iterations=profile["mcts"]["iterations"],
            ucb_c=profile["mcts"]["ucb_c"],
            rollout_strategy=profile["mcts"]["rollout_strategy"],
        )
        
        self.style = profile["style"]
    
    def select_pattern(self, state, player):
        # 调用父类 MCTS
        pattern = super().select_pattern(state, player)
        
        # 风格化后处理
        return self._apply_style(state, player, pattern)
    
    def _apply_style(self, state, player, pattern):
        """应用风格化规则。"""
        if pattern is None:
            return None
        
        # 炸弹吝啬：如果是炸弹，检查是否真的需要
        if self._is_bomb(pattern):
            if not self._should_use_bomb(state, player, pattern):
                # 改为过牌或出小牌
                return None
        
        # 控场节奏：优先出能控场的牌
        # 配合意识：队友领先时过牌
        # 漂牌决策：最后几张牌时规划5张+级牌炸弹
        
        return pattern
```

#### 方案 B：组合模式（更灵活，但复杂）

创建 `StyleModifier` 类，包装任何策略：

```python
class StyleModifier:
    def __init__(self, base_strategy, style_params):
        self.base = base_strategy
        self.style = style_params
    
    def select_pattern(self, state, player):
        pattern = self.base.select_pattern(state, player)
        return self._modify(pattern, state, player)
```

**推荐方案 A**：更简单直接，符合当前代码风格。

### Profile 加载机制

```python
import json
import os
from pathlib import Path

def load_profile(name: str) -> dict:
    """加载 AI 风格配置文件。
    
    Args:
        name: 配置文件名（如 "dachangsheng.json" 或 "dachangsheng"）
    
    Returns:
        配置字典
    """
    if not name.endswith(".json"):
        name += ".json"
    
    # 查找顺序：
    # 1. 包内路径
    # 2. 用户自定义路径（未来扩展）
    
    package_dir = Path(__file__).parent / "profiles"
    profile_path = package_dir / name
    
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found: {name}")
    
    with open(profile_path, "r", encoding="utf-8") as f:
        return json.load(f)
```

### 风格化实现细节

#### 1. 炸弹吝啬 (bomb_threshold)

```python
def _should_use_bomb(self, state, player, bomb_pattern):
    """判断是否应该使用炸弹。
    
    戴长胜风格：只在真正必要时才用炸弹。
    """
    # 如果队友已经头游，无需再出炸弹
    if self._teammate_is_first(state, player):
        return False
    
    # 如果对手即将获胜（手牌<=3），必须用炸弹阻止
    opponent_min_cards = min(
        state.hand_size(p) for p in range(4)
        if not is_teammate(p, player) and state.hand_size(p) > 0
    )
    if opponent_min_cards <= 3:
        return True
    
    # 根据 bomb_threshold 决定
    # threshold 越高，越不愿意用炸弹
    urgency = self._calculate_urgency(state, player)
    return urgency > self.style["bomb_threshold"]
```

#### 2. 控场节奏 (control_priority)

在 MCTS evaluation 时，给"能压制对手"的牌型加分：

```python
def _evaluate_result_with_style(self, state, root_player):
    """评估结果（加入风格化考量）。"""
    base_score = super()._evaluate_result(state, root_player)
    
    # 控场奖励：如果我方控制了出牌权，加分
    if self._our_team_controls(state, root_player):
        base_score += 0.1 * self.style["control_priority"]
    
    return base_score
```

#### 3. 配合意识 (teammate_awareness)

```python
def _apply_style(self, state, player, pattern):
    # 队友领先且手牌少，主动让牌
    partner = partner_of(player)
    if (state.hand_size(partner) <= 5 and 
        self._partner_is_winning(state, player)):
        # 更高概率过牌
        if random.random() < self.style["teammate_awareness"]:
            return None
    
    return pattern
```

#### 4. 漂牌决策 (drift_bonus)

```python
def _should_plan_for_drift(self, state, player):
    """判断是否应该规划漂牌。
    
    漂牌条件：最后一手是 5张+ 级牌炸弹。
    """
    hand_size = state.hand_size(player)
    
    # 只有手牌剩余 10 张以内才考虑漂牌
    if hand_size > 10:
        return False
    
    # 检查是否有可能组成 5张+ 级牌炸弹
    level_cards = [c for c in state.hands[player] if c.rank == state.level]
    
    if len(level_cards) >= 4:
        # 有机会漂牌，提升评估分数
        return True
    
    return False
```

## 实现步骤

### 步骤 1：创建 Profile 文件

**文件**：`src/guandan/ai/profiles/dachangsheng.json`

### 步骤 2：实现 Profile 加载器

**文件**：`src/guandan/ai/profiles/__init__.py`

功能：
- `load_profile(name) -> dict`
- 验证 schema
- 错误处理

### 步骤 3：实现 DaiChangshengStrategy

**文件**：`src/guandan/ai/strategies/dachangsheng.py`

功能：
- 继承 `ProfessionalStrategy`
- 加载 profile
- 实现风格化方法

### 步骤 4：注册到工厂

**文件**：`src/guandan/ai/strategy.py`

修改：
```python
_STRATEGIES: Dict[int, str] = {
    # ...
    4: "guandan.ai.strategies.dachangsheng.DaiChangshengStrategy",
}
```

### 步骤 5：编写测试

**文件**：`tests/test_dachangsheng.py`

测试：
- Profile 加载
- 风格化参数应用
- 炸弹吝啬行为
- 配合意识
- 策略集成

### 步骤 6：更新文档

- README.md：M4 完成
- CHANGELOG.md：v0.5.0 条目
- ADR-0003：风格化 AI 设计（可选）

## 参数调优

### 默认参数（dachangsheng.json）

```json
{
  "name": "戴长胜",
  "difficulty": 4,
  "description": "炸弹吝啬、控场节奏、配合意识、漂牌决策",
  "mcts": {
    "iterations": 150,
    "ucb_c": 1.41,
    "rollout_strategy": 2,
    "top_actions": 5
  },
  "style": {
    "bomb_threshold": 0.80,
    "control_priority": 0.90,
    "teammate_awareness": 0.95,
    "drift_bonus": 0.70,
    "pass_probability_multiplier": 1.2
  }
}
```

### 参数含义

| 参数 | 范围 | 含义 | 戴长胜值 |
| --- | --- | --- | --- |
| `bomb_threshold` | 0-1 | 使用炸弹的紧迫度阈值 | 0.80（高，吝啬） |
| `control_priority` | 0-1 | 控场优先级权重 | 0.90（高） |
| `teammate_awareness` | 0-1 | 队友协作意识 | 0.95（极高） |
| `drift_bonus` | 0-1 | 漂牌追求度 | 0.70（高） |
| `pass_probability_multiplier` | >0 | 过牌概率乘数 | 1.2（更倾向让牌） |

## 性能考虑

### 时间复杂度

- M3（档3）：100 迭代，约 2-5 秒
- M4（档4）：150 迭代，约 3-8 秒

**可接受理由**：
- 最高难度，用户预期需要等待
- 风格化计算开销小（主要是 MCTS）
- 未来可优化（缓存、并行）

### 优化方向

1. **缓存**：相同状态不重复搜索
2. **并行**：多线程 MCTS
3. **渐进深化**：时间限制内尽量多搜索
4. **剪枝**：更激进的动作筛选

## 测试策略

### 单元测试

1. **Profile 加载**：
   - 加载成功
   - 文件不存在抛异常
   - Schema 验证

2. **风格化行为**：
   - 炸弹吝啬：档4比档3更少用炸弹
   - 配合意识：队友领先时更倾向过牌
   - 漂牌决策：最后几张牌时规划特定牌型

### 集成测试

1. **对战测试**：
   - 档4 vs 档3：档4 应有相当或更高胜率
   - 档4 vs 档2：档4 应完胜
   - 档4 自己打自己：验证决策稳定性

2. **性能测试**：
   - 每步决策时间 < 10 秒
   - 完整对局无崩溃

3. **风格测试**：
   - 统计炸弹使用频率（应低于档3）
   - 统计让牌次数（应高于档3）

## 验收标准

### 功能标准

- ✅ DaiChangshengStrategy 实现 `AIStrategy` 接口
- ✅ `make_strategy(4)` 返回档4实例
- ✅ TUI 难度选择屏档4可进入游戏
- ✅ CLI `--difficulty 4` 可运行
- ✅ Profile 文件正确加载

### 质量标准

- ✅ 161+ 个测试全部通过
- ✅ 新增 8+ 个档4测试
- ✅ ruff/mypy 静态检查通过
- ✅ 对战档4 vs 档3，档4 胜率 ≥ 50%

### 风格标准

- ✅ 炸弹使用率低于档3（统计验证）
- ✅ 队友协作行为明显（让牌频率高）
- ✅ 决策质量稳定（无明显愚蠢决策）

## 风险与缓解

### 风险 1：风格化难以量化

**问题**：风格是主观的，难以客观验证

**缓解**：
- 通过统计指标验证（炸弹使用率、让牌频率）
- 对战测试验证整体强度
- 用户反馈迭代

### 风险 2：计算时间过长

**问题**：150 迭代可能导致 10+ 秒等待

**缓解**：
- 设置时间上限（如 10 秒）
- 渐进深化：时间内尽量多搜索
- 提示用户这是最高难度

### 风险 3：风格参数难以调优

**问题**：不清楚最优参数值

**缓解**：
- 从合理默认值开始（0.7-0.9）
- 通过对战测试迭代调整
- 未来可支持自定义 profile

## 未来扩展

### M5+ 可能改进

1. **多个风格 Profile**：
   - `aggressive.json`（激进型）
   - `defensive.json`（防守型）
   - `balanced.json`（平衡型）

2. **自适应风格**：
   - 根据对手风格动态调整
   - 学习用户习惯

3. **更多维度**：
   - 冒险度（risk_tolerance）
   - 进攻性（aggressiveness）
   - 计算深度（thinking_time）

## 总结

M4 通过 **IS-MCTS + 风格化参数** 实现"戴长胜"AI：
- 继承档3的 MCTS 搜索能力
- 通过 JSON profile 定义风格
- 在评估和决策中应用风格规则
- 目标：最强且有特色的 AI

简单、可扩展、易于调优。

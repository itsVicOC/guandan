# AI Profiles

本目录用于存放 AI 风格配置文件（M4 阶段实现）。

## 规划

### 档位 4：职业（M3）
- 使用 IS-MCTS（信息集蒙特卡洛树搜索）
- 不需要配置文件，纯算法实现

### 档位 5：戴长胜（M4）
- 风格化 AI，致敬戴长胜牌风
- 配置文件示例：`dachangsheng.json`

## 配置文件格式（草案）

```json
{
  "name": "戴长胜",
  "difficulty": 5,
  "style": {
    "bomb_threshold": 0.8,
    "control_priority": 0.9,
    "teammate_awareness": 0.95,
    "drift_aggressiveness": 0.7
  },
  "description": "炸弹吝啬、控场节奏、配合意识、漂牌决策"
}
```

## 当前状态

- **M2 完成**：档 0/1/2 已实现（新手/进阶/高手）
- **M3 待实现**：档 3（职业，IS-MCTS）
- **M4 待实现**：档 4（戴长胜，风格化配置）

## 使用方式

配置文件将在 M4 阶段通过 `make_strategy(4)` 加载并应用到 AI 决策中。

## 参考

- `src/guandan/ai/strategy.py` - AI 策略接口
- `src/guandan/ai/valuation.py` - 手牌估值系统
- `pyproject.toml` - package-data 配置

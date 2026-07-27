# AI Profiles

本目录用于存放 AI 风格配置文件。

## 档位

### 档位 3：职业（M3）
- 使用 IS-MCTS（信息集蒙特卡洛树搜索）
- 不需要配置文件，纯算法实现

### 档位 4：戴长胜（M4+）
- 风格化 AI，致敬戴长胜牌风
- 配置文件示例：`dachangsheng.json`

## 配置文件格式

```json
{
  "name": "戴长胜",
  "difficulty": 4,
  "mcts": {
    "iterations": 96,
    "time_budget_ms": 420,
    "ucb_c": 1.15,
    "prior_weight": 0.22,
    "rollout_strategy": 2,
    "top_actions": 12,
    "max_depth": 14,
    "hand_threshold": 10,
    "rollout_max_turns": 48,
    "widening_c": 2.0,
    "widening_alpha": 0.5
  },
  "style": {
    "bomb_threshold": 0.25,
    "control_priority": 0.5,
    "teammate_awareness": 0.85,
    "pass_probability_multiplier": 1.2
  },
  "description": "炸弹审慎、控场节奏、配合意识"
}
```

## 当前状态

- **M2 完成**：档 0/1/2 已实现（新手/进阶/高手）
- **M3 完成**：档 3（职业，团队感知 SO-ISMCTS）
- **M4 完成**：档 4（戴长胜，自对弈选择的稳健搜索先验与更高预算）
- **v0.7.0-beta.3 公测版**：已完成 M7 AI 对战基准与策略调优收口，包含 MCTS 性能闸门、规则驱动候选出牌、终局优先级、短手牌拦截和 TUI 主流程/回合顺序稳定性回归

## 使用方式

配置文件会通过 `make_strategy(4)` 加载并应用到 AI 决策中。

## 参考

- `src/guandan/ai/strategy.py` - AI 策略接口
- `src/guandan/ai/valuation.py` - 手牌估值系统
- `pyproject.toml` - package-data 配置

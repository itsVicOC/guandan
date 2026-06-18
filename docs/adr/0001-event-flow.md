# ADR-0001: 事件流协议

## 状态
提议中（2026-06-02）

## 背景
掼蛋游戏的**对局过程**是一连串离散事件（发牌、出牌、过牌、报牌、进贡、还贡、抗贡、升级、过 A，以及历史兼容事件），
这些事件是 engine / tui / ai / storage 之间的**唯一通信协议**。

如果走"GameState 字段变更"的方案，后期加新功能（报牌、抗贡等）就要反复改 GameState schema，
每次改都让历史回放/断点档失效。

## 决策
引入显式 `engine.events` 事件流：

| 事件 | 触发时机 | 关键字段 |
| --- | --- | --- |
| `ShuffleDeal` | 一局开始时 | level, hands, wild_card |
| `TurnPlayed` | 玩家出牌 | player_idx, pattern |
| `Pass` | 玩家过牌 | player_idx |
| `Claim` | 玩家报牌 | player_idx, count |
| `Tribute` | 进贡 | from_idx, to_idx, card |
| `ReturnTribute` | 还贡 | from_idx, to_idx, card |
| `ResistTribute` | 抗贡 | player_idx |
| `Drift` | 历史兼容事件（当前规则不再产生） | player_idx, level |
| `LevelUp` | 升级 | team, delta |
| `GameOver` | 一局结束 | winner_team, final_levels |

## 后果
- ✅ 加新规则只需加新事件类型，不动 GameState
- ✅ 回放本质就是事件序列
- ✅ 断点档 = 事件序列 + 当前快照
- ✅ AI 输入 = 事件流，输出 = 决策事件
- ❌ 事件 schema 一旦发布需严格向后兼容（用版本号）

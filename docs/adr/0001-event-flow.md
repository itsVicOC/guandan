# ADR-0001: 事件流协议

## 状态
已采纳（2026-06-02 提议，2026-06-05 起为 engine / ui / storage 的实际协议）

## 背景
掼蛋游戏的**对局过程**是一连串离散事件（发牌、出牌、过牌、报牌、进贡、还贡、抗贡、升级、过 A，以及历史兼容事件），
这些事件是 engine / tui / ai / storage 之间的**唯一通信协议**。

如果走"GameState 字段变更"的方案，后期加新功能（报牌、抗贡等）就要反复改 GameState schema，
每次改都让历史回放/断点档失效。

## 决策
引入显式 `engine.events` 事件流：

| 事件 | 触发时机 | 关键字段 |
| --- | --- | --- |
| `ShuffleDeal` | 一局开始时 | level, wild_card, hand_sizes, first_player, seed, team_levels |
| `TurnPlayed` | 玩家出牌 | player, pattern, hand_remaining |
| `Pass` | 玩家过牌 | player, hand_remaining |
| `Claim` | 玩家报牌 | player, count |
| `TributeSent` | 进贡 | from_player, to_player, card, reason |
| `TributeReturned` | 还贡 | from_player, to_player, card, reason |
| `TributeResisted` | 抗贡 | player, team, reason |
| `Drift` | 历史兼容事件（当前规则不再产生） | player, bonus_levels |
| `LevelUp` | 升级 | team, new_level, delta |
| `GameOver` | 一局结束 | finish_order, team_levels, drift, guo_a, winner_team |

字段名以 `src/guandan/engine/events.py` 为准；本表曾使用 `*_idx` 与
`Tribute`/`ReturnTribute`/`ResistTribute` 等未实现的命名。

## 后果
- ✅ 加新规则只需加新事件类型，不动 GameState
- ✅ 回放本质就是事件序列
- ✅ 断点档 = 事件序列 + 当前快照
- ✅ AI 输入 = 事件流，输出 = 决策事件
- ❌ 事件 schema 一旦发布需严格向后兼容（用版本号）

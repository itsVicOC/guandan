# 变更日志

## [0.1.0] - 2026-06-02

### 已完成（M0a：规则引擎 + CLI 跑通完整对局）

#### 核心功能
- 牌具：2 副牌 108 张（4 种花色 × 13 点数 × 2 + 4 王）
- 牌型识别 10 种：单张 / 对子 / 三张 / 三带二 / 顺子（含 A 双向）/ 连对 / 钢板 / 4-7 张炸弹 / 同花顺 / 四王炸弹
- 逢人配（红心级牌）可正确替换，单遍扫描即可枚举所有合法牌型
- 级牌制度（2..A），级牌可单出
- 完整对局流程：发牌 → 出牌 → 过牌 → 轮转 → 上游判定 → 升级 / 双上 / 双下
- 漂牌判定（5 张+级牌炸弹）
- 进贡 / 还贡 / 抗贡（大王×2 + 小王×2 可抗贡）
- 报牌机制（手牌 ≤ 10 张自动提示）
- 不可变事件流：ShuffleDeal / TurnPlayed / Pass / Claim / Tribute* / Drift / LevelUp / GameOver

#### 工程
- Python 3.9+ 兼容（用 `Union` 替代 3.10+ 的 `X | Y`）
- pytest + hypothesis 测试，**99 个测试全过**
- 包结构：engine / ai / tui / storage / utils
- pyproject.toml（setuptools + 依赖：textual / rich）
- .gitignore 完整

#### CLI（v0.1.0 简化版）
- 命令行启动：`python -m guandan.cli [--level 2..14] [--first 0..3] [--seed N]`
- 显示级牌、逢人配、4 家手牌
- 真人玩家手牌 + 出牌提示
- 贪心 AI（最快可压牌型）— M2 阶段重写
- 5 局冒烟测试平均 130 轮完成

### 计划中（后续 milestone）
- M1：textual TUI 替换 CLI
- M2：AI 1-3 档（贪心 + 记牌 + 简单估值）
- M3：AI 4 档（IS-MCTS）
- M4：戴长胜 AI（风格化 profile）
- M5：持久化（profile / replay / savegame）
- M6：调优 & v1.0 发布

# 变更日志

## [Unreleased]

### M7 AI 调优起步

#### AI 策略
- 新增 `guandan.ai.benchmark` 对战基准工具，可按座位混合难度跑 AI-only 对局并输出完成率、胜队、平均回合、炸弹数与最终升级。
- AI benchmark 支持 `--json` 机器可读输出，便于保存调参结果并做后续胜率/耗时回归比较。
- AI benchmark 支持 `--compare baseline.json current.json`，可输出完成率、胜率、平均回合、耗时和炸弹数变化。
- AI benchmark 对比新增回归门禁参数，可在完成率明显下降、平均耗时或平均回合数上升超阈值时返回失败码。
- 抽取 `engine.trick` 当前牌墩 helper，统一状态机、AI、TUI 对当前桌面出牌者、最大牌玩家和锁定过牌玩家的判断。
- 职业 / 戴长胜策略不再被统一概率过牌二次覆盖，策略选出的高价值压牌会直接执行，过牌决策回归策略内部。
- MCTS rollout 结果评分从“只看头游队伍”升级为结合名次升级收益、头游归属和未完成局面手牌压力的连续评分。
- MCTS rollout 改为轻量贪心模拟，并将默认 rollout 上限调为 40 手，降低职业档在 TUI/benchmark 中的响应时间。
- 职业档默认 MCTS 预算调整为 60 次迭代、top-4 动作，并限制 rollout 只在 10 张以内做完整手牌识别，减少长等待。
- AI 估值与概率过牌统一按级牌实际强度判断，避免非红桃级牌被当作普通小牌消耗或低估桌顶级牌压力。
- 进阶及以上 AI 领牌时会更主动打出自然顺子、连对、钢板和三带二来减少手数，同时保留逢人配保护。
- 概率过牌新增短手牌拦截：对手只剩 1 张且自己有合法响应时不再随机过牌放跑。
- 高手/戴长胜协作策略在队友领先但对手报单时会优先护航，避免过度让牌给对手出完机会。
- 对手报单时，进阶及以上 AI 领牌会优先选择对子/三张等非单牌，减少单张放跑风险。
- AI 候选估值排序复用结构牌评分缓存，减少重复牌型识别带来的 TUI/benchmark 响应开销。
- 职业档 MCTS 关键局面闸门只按对手短手牌触发，不再因队友短手牌误入 MCTS。
- AI leader 兜底出牌返回值修正为真实出牌，并按级牌强度选择兜底单张，避免误报过牌或浪费级牌。
- 抽取 AI 对手手牌上下文 helper，统一估值、概率过牌、职业档和戴长胜策略的对手短手牌判断。
- 高手策略每次决策只构建一次记牌器，避免按候选重复扫描历史。
- 记牌器普通点数总数修正为双副牌 8 张，避免高手策略误判绝张。
- 戴长胜档炸弹吝啬策略不再拦截可直接出完的炸弹，避免队友已头游时错过终局牌。
- 戴长胜档配合意识不再覆盖一手出完，避免队友领先时错过自己的终局响应。
- 高手策略与 MCTS rollout 统一一手出完优先级，避免队友领先协作分压过终局出牌。

#### 测试
- 新增 AI benchmark / benchmark 对比与门禁测试、当前 trick helper 回归测试、职业档随机过牌覆盖测试和 MCTS 评分测试。
- `ruff check src tests` 通过。
- `mypy src` 通过。
- `pytest`：276 个测试全过。

## [0.7.0-beta.2] - 2026-06-13

### 公测版补丁 - 回合顺序与桌面显示修复

#### TUI
- 修复牌局页从整局历史反查当前桌面出牌者/过牌者的问题，避免旧轮次过牌或相同牌型污染当前轮显示。
- 当前桌面现在只基于当前 trick 尾部事件重建出牌者和过牌顺序，牌权切换后的显示更稳定。
- 状态栏“最大牌玩家”和中央桌面玩家标注统一使用当前 trick 解析结果。

#### 规则回归
- 补充任意座位先手出牌后必须按逆时针推进的规则层测试。
- 补充后手赢得牌权并开启新一轮后仍按逆时针推进的规则层测试。
- 补充任意真人座位下，AI 新 leader 连续行动必须按逆时针推进到真人回合的 TUI 回归测试。

#### 验证
- `ruff check src tests` 通过。
- `mypy src` 通过。
- `pytest`：237 个测试全过。

#### 发布
- 项目状态更新为 `v0.7.0-beta.2 / 公测版`。
- Python 包版本更新为 `0.7.0b2`。

## [0.7.0-beta.1] - 2026-06-10

### 公测版 - 稳定性与发布收口

#### 牌局稳定性
- 修复 TUI 中 AI 作为新一轮领牌方时，只出一手后没有继续推进后续 AI 行动，导致牌局可能卡在 AI 回合的问题。
- AI 自动行动现在会持续推进到轮到真人、牌局结束，或达到单次 UI 调度上限；达到上限时会继续异步调度，避免长时间阻塞界面。
- AI 行动日志改为从事件历史识别实际出牌/过牌，避免桌面轮次变化时误判 AI 行为。

#### 测试
- 新增 TUI 回归测试，覆盖 AI 领牌后继续推进到真人回合的场景。
- `ruff check src tests` 通过。
- `mypy src` 通过。
- `pytest`：233 个测试全过。

#### 发布
- 项目状态更新为 `v0.7.0-beta.1 / 公测版`。
- Python 包版本更新为 `0.7.0b1`。
- README、TUI 标题、CLI 标题与 AI profile 文档同步公测状态。

## [0.6.6] - 2026-06-09

### M6 调优 - AI 策略与 TUI 视觉收口

#### AI 策略
- 新增规则驱动的 AI 候选生成器：AI 统一复用规则层 `detect_patterns()` 识别合法牌型。
- 修复 AI 不会用同型顺子、连对、钢板、三带二压牌的问题。
- 候选出牌支持 10 张炸弹，并与当前炸弹/同花顺比较规则保持一致。
- 进阶、高手、职业和 MCTS 搜索共享新的候选出牌池，减少 AI 与规则引擎脱节。
- 职业策略的一手出完判断直接识别完整手牌，避免被 Top-N 候选截断漏掉。
- 手牌估值新增结构保护：减少随意拆顺子、连对、钢板和三带二。
- 概率过牌策略改进：考虑一手出完、队友领牌、对手剩余手牌、炸弹成本和结构牌收益。
- 戴长胜 profile 的 `pass_probability_multiplier` 正式接入出牌流程。

#### 规则与稳定性
- 修复 MCTS 确定化牌池中大小王 suit 错误，确保 `is_joker` 判断正确。
- 修复高手策略队友领先判断使用对象身份比较的问题，深拷贝/存档恢复后仍可正确协作。
- 修复四王不能再压四王的比较漏洞。
- 牌型识别去重保留同 rank 但实际带牌不同的三带二等候选，便于 AI 做成本选择。

#### TUI
- 重做首页视觉：深色牌桌风格、座位示意、规则摘要和清晰的操作区。
- 难度选择页同步首页风格，改为双栏面板并突出本局级牌。
- 牌局页统一状态栏、对手区、中央桌面、手牌区和行动日志的视觉层级。
- 手牌区保留中文花色展示，并增加简洁操作提示。

#### 验证
- `ruff check src tests` 通过。
- `mypy src` 通过。
- `pytest`：232 个测试全过。

## [0.6.5] - 2026-06-09

### 规则修复 - 炸弹与同花顺口径

- 普通炸弹口径更新为 4-10 张，允许包含逢人配补牌。
- 同花顺可压 4 张普通炸弹，或同为 5 张的普通炸弹。
- 同花顺不能压 6 张及以上普通炸弹。
- 补充炸弹和同花顺比较测试。

## [0.6.4] - 2026-06-09

### 规则修复 - 牌型识别对齐确认口径

- 同花顺优先于普通顺子识别。
- 三带二不允许三张和对子同点；5 张同点按炸弹处理。
- 两张大王或两张小王可作为三带二的带二对子。
- 逢人配可补连对和钢板。
- 级牌强度不作用于顺子、连对、钢板、同花顺比较；例如打 5 时，A2345 仍是最小顺子。

## [0.6.3] - 2026-06-09

### 规则修复 - 王对子与重复牌选择

- 允许两张大王或两张小王作为对子出牌。
- 修复重复牌/重复王选择时被集合去重导致少出牌的问题。
- TUI 选中两个大王或两个小王时能正确组成对子。

## [0.6.2] - 2026-06-09

### 规则修复与 MCTS 性能闸门

#### 规则修复
- 修复出牌方向为逆时针：东 → 北 → 西 → 南 → 东。
- 修复当前最大牌玩家收轮后的 turn 推进问题。
- 修复级牌单张比较：当前级牌作为最大非王牌，可压普通高点数单牌。

#### AI 性能
- 职业 / 戴长胜策略新增 MCTS 性能闸门：
  - 前中期大手牌阶段使用高手策略快速决策。
  - 手牌进入阈值或对手进入关键手牌数后再启用 MCTS。
  - 可一次出完时直接走 fast path，减少无意义搜索。
- MCTS rollout 新增 `rollout_max_turns` 上限，降低单次搜索成本。
- 戴长胜 profile 调整为更适合本地 TUI 的默认参数：40 次迭代、top-4 动作、10 张以内启用 MCTS。
- 新增测试覆盖 MCTS 性能闸门和 profile 参数读取。

## [0.6.1] - 2026-06-08

### M5.1 完成 - 续局恢复与质量收口

#### 断点续局
- 存档写入完整 `GameState` 快照。
- `LoadSaveScreen` 的“继续游戏”恢复真实对局状态并进入牌桌。
- 事件反序列化兼容 `PatternType` 名称和值，并保留 `wild_used` / `suit`。

#### CLI / Smoke
- CLI 支持 `--difficulty 0..4`。
- 修复 `guandan.smoke` 调用 AI 策略时缺少 strategy/rng 的问题。

#### 规则与文档
- README、规则文档与实现对齐：炸弹不直接增加升级数，漂牌另计。
- 版本号统一到 `0.6.1`。

#### AI 调优
- 戴长胜策略补上漂牌决策：
  - 最后一手可打出 5 张以上级牌炸弹时优先追求漂牌。
  - 非终局跟牌时尽量保留可漂的级牌炸弹材料。

#### 质量
- `ruff check src tests` 通过。
- `mypy src` 通过。
- `pytest`：195 个测试全过。
- `.hypothesis/` 加入 `.gitignore`。

## [0.6.0] - 2026-06-05

### M5 完成 - 持久化系统

#### 存储模块（完整实现）
- **新增 storage 包**（`src/guandan/storage/`）：
  - `paths.py`：路径管理（`~/.guandan/`）
  - `serialization.py`：事件序列化/反序列化
  - `profile.py`：用户配置和统计
  - `savegame.py`：游戏存档（断点续局）
  - `history.py`：历史记录（对局回放）

#### 存储结构
```
~/.guandan/
├── profile.json      # 用户配置和统计
├── savegame.json     # 当前未完成的对局
└── history/          # 历史对局记录
    ├── 2026-06-05_143521_game001.json
    └── ...
```

#### Profile 功能
- 用户偏好（默认难度、提示开关）
- 统计数据（总局数、胜率、分档位统计）
- 自动更新时间戳

#### Savegame 功能
- 保存完整事件流（可重建状态）
- 保存状态快照（快速显示）
- 单个存档（对局结束后自动删除）

#### History 功能
- 保存完整对局记录
- 提取结果元数据（快速查询）
- 支持回放（完整事件流）
- 按时间倒序列表

#### TUI 集成（完整实现）
- 更新 **HistoryScreen**：显示最近 20 场对局
- 更新 **LoadSaveScreen**：显示存档信息、删除存档
- 更新 **GameScreen**：
  - 游戏结束时自动保存历史和统计
  - 退出未完成游戏时保存存档
  - 追踪对局元数据（game_id、seed、时长）

#### 端到端功能
- ✅ 完整对局自动保存历史和统计
- ✅ 中途退出自动保存存档
- ✅ 历史屏显示对局记录
- ✅ 存档屏显示/删除存档
- ✅ 存档加载功能（v0.6.1 补齐）

#### 测试
- 新增 20 个存储测试（`tests/test_storage.py`）：
  - 序列化往返（6 个测试）
  - Profile 管理（5 个测试）
  - Savegame 管理（4 个测试）
  - History 管理（5 个测试）
- **总计 192 个测试全过**（172 既有 + 20 新增）

#### 文档
- 更新 README.md：M5 完成
- 更新 CHANGELOG.md：v0.6.0 条目

## [0.5.0] - 2026-06-05

### M4 完成 - AI 档 4 戴长胜（风格化）

#### 新增 Profile 系统
- **风格化配置**：通过 JSON 文件定义 AI 风格参数
- **配置文件**：`src/guandan/ai/profiles/dachangsheng.json`
  - MCTS 参数：迭代次数 150、UCB 常数 1.41、Rollout 策略档 2
  - 风格参数：炸弹吝啬 0.80、控场优先 0.90、配合意识 0.95、漂牌追求 0.70

#### 档 4 戴长胜策略（DaiChangshengStrategy）
- 继承档 3 职业策略（IS-MCTS）
- 加载 profile 定义风格参数
- 实现风格化决策：
  1. **炸弹吝啬**：不轻易出炸弹，保留控场能力（bomb_threshold=0.80）
  2. **控场节奏**：优先控制出牌节奏
  3. **配合意识**：队友领先时高概率让牌（teammate_awareness=0.95）
  4. **漂牌决策**：主动追求5张+级牌炸弹的最后一手（drift_bonus=0.70）

#### Profile 加载器
- **模块**：`src/guandan/ai/profiles/__init__.py`
- **功能**：
  - `load_profile(name)` - 从 JSON 加载配置
  - 验证配置格式
  - 错误处理（文件不存在、格式错误）

#### 策略工厂更新
- `make_strategy(4)` 返回 DaiChangshengStrategy 实例
- 所有 5 档 AI 已实现（0/1/2/3/4）

#### 测试
- 新增 11 个戴长胜测试（`tests/test_dachangsheng.py`）：
  - Profile 加载：成功加载、文件不存在、Schema 验证
  - 策略初始化：属性正确、使用 profile 参数
  - 风格化行为：炸弹识别、队友判断、对手手牌统计
- **总计 172 个测试全过**（161 既有 + 11 新增）

#### 性能
- 每步决策时间：约 3-8 秒（150 迭代）
- 相比档 3 更强（更多迭代 + 风格化）

#### 文档
- 更新 README.md：M4 完成，所有档位已实现
- 更新 CHANGELOG.md：v0.5.0 条目

## [0.4.0] - 2026-06-05

### M3 完成 - AI 档 3 职业级（IS-MCTS）

#### 新增 `guandan.ai.mcts` 包
- **算法**：IS-MCTS（Information Set Monte Carlo Tree Search，信息集蒙特卡洛树搜索）
- **模块结构**：
  - `node.py`：MCTSNode 数据结构（状态、访问次数、胜率、子节点）
  - `determinize.py`：信息集确定化（根据已出牌推断其他玩家可能手牌）
  - `search.py`：MCTS 主循环（Selection/Expansion/Simulation/Backpropagation）

#### 档 3 职业策略（ProfessionalStrategy）
- 使用 IS-MCTS 进行决策，能够前瞻多步
- 算法流程：
  1. **Determinization**：生成其他玩家可能的手牌分配
  2. **MCTS 搜索**：在确定化的世界中运行树搜索
  3. **UCB1 选择**：平衡探索与利用
  4. **快速 Rollout**：用档 1 策略模拟到游戏结束
  5. **回传更新**：更新节点访问次数和胜率
- 参数配置：
  - 迭代次数：100（可调，平衡速度和质量）
  - UCB1 常数：1.41（sqrt(2)）
  - 候选动作数：5（剪枝）
  - Rollout 策略：档 1（进阶）

#### 策略工厂更新
- `make_strategy(3)` 返回 ProfessionalStrategy 实例
- 档 4（戴长胜）仍抛 `AINotImplementedError`（M4 待实现）

#### 测试
- 新增 10 个 MCTS 测试（`tests/test_mcts.py`）：
  - 确定化：手牌数守恒、玩家手牌不变、随机性
  - UCB1：未访问节点优先、探索奖励
  - MCTS 搜索：正常运行、访问次数更新
  - 职业策略：返回有效牌型、合法出牌、属性正确
- **总计 161 个测试全过**（151 既有 + 10 新增）

#### 性能
- 每步决策时间：约 2-5 秒（100 迭代）
- 算法复杂度：O(iterations × depth × branching_factor)
- 剪枝策略：只考虑 top-5 候选动作

#### 文档
- 更新 README.md：M3 完成，档 3 职业已实现
- 新增 ADR-0002：IS-MCTS 算法选型

## [0.3.2] - 2026-06-05

### 改进 - 项目配置和文档完善

- 修复 ruff 配置：忽略中文全角符号警告（RUF002/RUF003）
- 重新安装开发依赖：mypy 1.19.1 现已可用
- 创建完整规则文档（docs/rules.md）：包含游戏概述、牌型说明、升级规则、特殊规则等
- 创建 AI profiles 目录（src/guandan/ai/profiles/）：为 M4 戴长胜风格化配置预留

验证：
- 151 个测试全部通过
- ruff 检查无中文全角符号误报
- pyproject.toml 配置与实际文件结构一致

## [0.3.1] - 2026-06-04

### Hotfix - 过牌锁住规则（spec 规则 3）

v0.3.0 发现的预存 bug：`pass_count` 计数器无法保证"过牌后本圈不能再出"。
- 0 出牌 → 1 过 → 2 出牌（重置 pass_count）→ 3 过 → 0 再出 → 1 已被重置可重新出
- 违反掼蛋 spec 规则 3：「一旦选择"过"，该玩家在本圈牌中将失去出牌机会」

#### 修复
- `GameState.pass_count: int` → `GameState.passed_players: set[int]`
- `pass_turn` 把当前玩家加入 `passed_players`，不重置
- `play_pattern` 检查 `player in passed_players` → 抛 `IllegalPlayError`
- 新增 `_next_active_player`：`pass_turn` 和 `play_pattern` 都用它推进 turn，跳过 finish_order + passed_players
- `_end_trick_or_jiefeng` 清空 `passed_players`（新一轮重新计数）

#### 行为
- 已过牌玩家在同一 trick 内再调 `play_pattern` 抛 `IllegalPlayError`
- turn 推进跳过已过牌玩家（去到下一个未过且未 finish 的玩家）
- 3 个非 leader 全过 → trick 结束，`passed_players` 清空 → 玩家在新 trick 重新可行动

#### 测试
- 新增 4 个测试（`TestPassedLockout`）：覆盖 spec 规则 3 的 4 个场景
- 总计 151 个测试全过

## [0.3.0] - 2026-06-04

### M2 完成 - AI 策略包（档 0/1/2）

#### 新增 `guandan.ai` 包
- **抽象**：`AIStrategy` Protocol（`name` / `difficulty` / `select_pattern`）
- **工厂**：`make_strategy(d: int) -> AIStrategy`，档 3/4 抛 `AINotImplementedError`
- **共享层**：
  - `greedy.select_min_winning(state, player)` —— 基础出牌选择（从 cli.py 抽出来、清理）
  - `valuation.estimate_pattern_cost(...)` —— 手牌价值评估（拆对/拆王/wild 浪费/炸弹溢价/完牌奖励）
  - `valuation.enumerate_candidate_plays(...)` —— top-N 候选出牌
  - `memory.PlayedTracker` —— 记牌器（已出牌 → remaining/in_someone_hand/bomb_count）
  - `stochastic.should_pass(...)` —— 概率过牌（注入 rng，测试可 seed）
  - `play.play_or_pass(state, player, strategy, rng)` —— CLI + TUI 共享的动作

#### 3 档策略
- **NoviceStrategy（档 0 新手）**：纯贪心 + 概率过牌（base=0.10, scale=0.60）
- **IntermediateStrategy（档 1 进阶）**：top-5 候选估值排序
- **AdvancedStrategy（档 2 高手）**：估值 + 协作分（队友领先时主动过牌）+ 记牌（关键 rank 绝张加成）

#### 引擎改动
- 把私有的 `_partner(player)` 提升为公开的 `partner_of(player)`
- 新增 `is_teammate(a, b)` 模块函数
- 内部接风 / 过 A 判定改用新 API（行为不变）

#### CLI 改动
- 删除 `_greedy_ai_select` / `_ai_play`（移到 `guandan.ai`）
- 新增 `--difficulty {0,1,2}` argparse 选项（默认 0）
- AI 行动通过 `guandan.ai.play_or_pass` 统一
- 遇 `AINotImplementedError` 友好退出（退出码 2）

#### TUI 改动
- `GameScreen.__init__` 注入 `self._strategy = make_strategy(difficulty)`，AI 牌桌标签动态显示档名
- `action_hint` 固定用档 1（进阶）策略（M2 决策）
- 难度选择屏档 3/4 弹 `ErrorModal`（"AI 档位未上线"）+ 不进入游戏
- 新增 `tui/screens/error.py` 通用错误 Modal屏
- App SUB_TITLE 升级为 `v0.3.0 · M2`

#### 测试
- 33 个新 AI 测试（`tests/test_ai.py`）覆盖：
  - 工厂 + DIFFICULTY_NAMES + AINotImplementedError
  - 贪心选择（leader / follower / 无法压 / 炸弹）
  - 估值（完牌奖励 / 拆对惩罚 / wild 浪费 / 炸弹溢价）
  - 候选枚举（leader / 排序）
  - 记牌器（remaining / in_someone_hand / bomb_count）
  - 概率过牌（leader 不过 / 无牌必过 / 桌顶越大越倾向过 / 确定性）
  - 策略差异化（Advanced 协作分 / Intermediate 估值）
  - `play_or_pass` 集成（leader 必出 / 协作分过牌）
- 6 个新引擎助手测试（`tests/test_engine_helpers.py`）
- **总计 147 个测试全过**（108 既有 + 39 新增）

## [0.2.0] - 2026-06-02

### M1 完成 - textual TUI 替换 CLI

#### 5 屏架构
- **MainMenuScreen** (主菜单)：5 个选项（开始新局 / 续局 / 战绩 / 规则 / 退出）+ 数字键快捷键
- **DifficultySelectScreen** (难度选择)：5 档 AI（新手/进阶/高手/职业/戴长胜）
- **GameScreen** (牌桌屏)：3 OpponentWidget + TableWidget + 玩家手牌 + 状态栏
- **RuleScreen** (规则说明)：完整规则可滚动
- **HistoryScreen / LoadSaveScreen**：M5 阶段实现的占位

#### GameScreen 交互
- 方向键（←/→/↑/↓）移动光标
- Space 选择/取消选牌
- Enter 出牌
- P 过牌
- T AI 提示
- B 报牌
- ? 查看规则
- Escape 返回

#### GameScreen 显示
- 4 家手牌（西/北/南为 AI，对家视角的"你"为真人）
- 中央出牌区（按出牌顺序展示）
- 玩家手牌按从大到小排序，光标 ▶ 选中 ■，已选 ★
- sub_title 显示当前状态（轮到你/等待 X 出牌/本局结束）

#### 关键 fix
- **textual 的 `_render` 是保留方法名**：自定义 widget 用此名会触发
  `get_content_height` 错误（visual=None）。重命名为 `_do_render` 解决。
  原因：textual 内部 Widget 在 mount 时会调用 `_render` 钩子来获取初始 visual。
- 同样原因，方法名不要用 `name` / `cursor` / `cards` / `selected` / `hand`（widget 内部属性）

#### 测试
- 106 个单元测试 + property-based 测试 全部通过
- TUI headless 端到端测试（pilot）：主菜单 → 难度选择 → 牌桌 → 玩家出牌 → AI 应答 ✓

## [0.1.2] - 2026-06-02

### 修复（按《掼蛋的接风判定与四名次的产生规则》文档）

#### 1. 接风（借风）规则
- **v0.1.1 错误**：玩家出完最后一手**立即**触发接风
- **v0.1.2 正确**：接风只在"出完手牌 + 无人压牌"**双重条件**下触发
  - play_pattern 出完手牌后**不再立即**切换 leader
  - 其他人可以选择压牌（继续这一轮）或过牌
  - 直到所有"能行动的非 leader 玩家"都过牌，才触发接风
  - 若最后一手被他人压了（即使压牌者随后也出完），不接风，由压牌者继续领出

#### 2. 游戏结束时机
- **v0.1.1 错误**：2nd 出完手牌时结束
- **v0.1.2 正确**：**3rd 出完手牌**时结束，剩余 1 人即末游
- `_next_player` 现在跳过已出完的玩家

#### 3. 升级规则（核心修正）
- **v0.1.1 错误**：双上 +3、双下 -3（双方各自升降）
- **v0.1.2 正确**（按文档）：只有头游方升级，对方不降级
  - 头游 + 二游（己方包揽前 2 名，"双下"）= **+3** 级
  - 头游 + 三游（己方队友是 3rd）= **+2** 级
  - 头游 + 末游（己方队友是末游）= **+1** 级
  - 加上本局头游方出的炸弹数（每多 1 个 +1）

#### 4. 过 A 规则
- **v0.1.1 错误**：升到 A 后下一局即过 A
- **v0.1.2 正确**：必须"双上"（头游 + 队友非末游，即头游+二游 或 头游+三游）才算过 A 成功
  - 若头游+末游（队友是末游）→ 冲 A 失败，头游方降回 2
  - `state.guo_a` 标记成功，`state.guo_a_failed` 标记失败

#### 5. 边界处理
- 引入 `_active_non_leader_count()`：当 1+ 个玩家已出完手牌时，"非 leader 玩家"= 仍能行动的非 leader 数
  - 例：4 人都在玩 → 3；1 个 finisher → 2；2 个 finisher → 1
- 引入接风对家也已出完的兜底：找下一个 active 玩家
- 漂牌逻辑保持原状

#### 6. 测试
- 106 个测试全过（新增 6 个文档规则测试）
- AI 5 局冒烟：167/156/161/151/130 轮，正确显示 3 finisher + 1 末游

## [0.1.1] - 2026-06-02

### 修复
- **接风规则** (v0.1.0 关键 bug)：头游产生后不停局，对家自动接风成为下一轮先手；继续打到二游产生才结束
- **完成顺序判定**：三游/末游按手牌数升序排（少者=三游，多者=末游），不再用统一手牌数排
- 漂牌判定：找上游玩家的**最后一手**（之前可能误判）
- LevelUp 事件在 delta 为负时也触发

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

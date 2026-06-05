# M3 实施计划：AI 档 3 职业级（IS-MCTS）

## 目标

实现档 3"职业"AI，使用 IS-MCTS（Information Set Monte Carlo Tree Search，信息集蒙特卡洛树搜索）算法。

## 背景分析

### 现有 AI 架构（M2）

**策略接口**：
```python
class AIStrategy(Protocol):
    name: str
    difficulty: int
    def select_pattern(state: GameState, player: int) -> Pattern | None
```

**已实现策略**：
- 档 0（新手）：纯贪心 + 概率过牌
- 档 1（进阶）：top-5 候选 + 估值排序
- 档 2（高手）：估值 + 协作分 + 记牌

**共享工具**：
- `greedy.select_min_winning` - 找能压桌面的最小牌
- `valuation.estimate_pattern_cost` - 估值（拆对/wild浪费/炸弹溢价）
- `valuation.enumerate_candidate_plays` - 枚举候选出牌
- `memory.PlayedTracker` - 记牌器
- `stochastic.should_pass` - 概率过牌
- `play.play_or_pass` - 统一的出牌/过牌动作

### 掼蛋游戏的特点

**不完全信息游戏**：
- 玩家只能看到自己的手牌
- 其他3家的手牌是隐藏信息
- 已出牌可以观测（通过 `state.history`）

**4人固定搭档**：
- 东↔西（player 0 & 2）同队
- 南↔北（player 1 & 3）同队
- 需要协作意识，不是纯竞争

**复杂的行动空间**：
- 每个玩家每回合可出的牌型数量可能很多
- 需要剪枝以保持计算可行性

**确定性规则**：
- 给定状态和行动，下一状态是确定的
- 适合树搜索

## IS-MCTS 算法设计

### 1. 信息集（Information Set）

**定义**：在不完全信息游戏中，信息集是"对当前玩家而言不可区分的所有状态集合"。

**掼蛋中的信息集**：
- 可观测：自己手牌、已出牌历史、桌面、finish_order、turn_index
- 不可观测：其他3家的手牌分配

**确定化（Determinization）**：
- 在搜索前，随机生成一种符合已知信息的"可能世界"
- 将其他3家的未出牌随机分配到3家手牌中
- 在这个确定化的世界中运行标准 MCTS

**多次确定化**：
- 运行多次 MCTS（每次用不同的确定化）
- 对所有确定化的结果求平均，得到最终决策

### 2. MCTS 四个阶段

```
1. Selection（选择）
   从根节点出发，用 UCB1 选择子节点，直到叶子节点

2. Expansion（扩展）
   如果叶子节点未完全展开，添加一个新子节点

3. Simulation（模拟/rollout）
   从新节点开始，用简单策略（如随机或贪心）快速玩到游戏结束

4. Backpropagation（回传）
   将模拟结果回传到路径上的所有节点，更新胜率统计
```

### 3. UCB1 公式

```
UCB1(node) = win_rate + C * sqrt(ln(parent_visits) / node_visits)
```

- `win_rate` = 该节点的平均胜率（exploitation，利用）
- 右侧 = exploration bonus（探索奖励）
- `C` = 探索常数（典型值 1.41，即 sqrt(2)）

### 4. 节点结构

```python
@dataclass
class MCTSNode:
    state: GameState           # 当前状态
    player: int                # 当前玩家
    parent: MCTSNode | None
    action: Pattern | None     # 从父节点到此节点的动作（None = pass）
    children: list[MCTSNode]
    visits: int = 0
    wins: float = 0.0          # 累计胜利值（从当前玩家视角）
    untried_actions: list[Pattern | None] = field(default_factory=list)
```

## 实现方案

### 方案选择：简化的 IS-MCTS

考虑到这是单机游戏（不是竞技对战），以及计算资源限制，采用**简化版 IS-MCTS**：

1. **单次确定化**：每次决策时只做1次确定化（不是多次平均）
   - 理由：计算更快，对单机游戏体验足够
   - 未来可通过参数调整确定化次数

2. **浅层搜索**：限制搜索深度和迭代次数
   - 迭代次数：100-500次（可调参数）
   - 深度限制：最多前瞻5-10个回合

3. **智能剪枝**：
   - 只考虑 top-N 候选牌型（利用现有的 `enumerate_candidate_plays`）
   - 过滤明显劣势的行动

4. **快速 rollout**：
   - Simulation 阶段用档 1（进阶）策略，不用随机
   - 理由：纯随机太弱，影响评估质量

### 模块结构

```
src/guandan/ai/
├── mcts/
│   ├── __init__.py
│   ├── node.py           # MCTSNode 数据结构
│   ├── determinize.py    # 信息集确定化
│   ├── search.py         # MCTS 主循环
│   └── ucb.py            # UCB1 计算
└── strategies/
    └── professional.py   # 档 3 策略类
```

### 核心算法伪代码

```python
class ProfessionalStrategy:
    def select_pattern(self, state: GameState, player: int) -> Pattern | None:
        # 1. 确定化：生成其他玩家的可能手牌分配
        determinized_state = determinize(state, player)
        
        # 2. MCTS 搜索
        root = MCTSNode(state=determinized_state, player=player)
        for _ in range(NUM_ITERATIONS):
            # Selection
            node = select(root)
            
            # Expansion
            if not node.is_terminal() and node.is_fully_expanded():
                node = expand(node)
            
            # Simulation
            result = simulate(node)
            
            # Backpropagation
            backpropagate(node, result)
        
        # 3. 选择最佳行动（访问次数最多）
        best_child = max(root.children, key=lambda c: c.visits)
        return best_child.action
```

### 确定化策略

```python
def determinize(state: GameState, player: int) -> GameState:
    """为其他3家分配可能的手牌。
    
    约束：
    1. 每家手牌数 = state.hand_size(p)
    2. 已出牌不能再分配
    3. 从未出牌中随机抽取
    """
    # 1. 统计未出牌
    played_tracker = PlayedTracker.from_history(state)
    unplayed_cards = []
    for rank in ALL_RANKS:
        remaining = played_tracker.remaining(rank)
        unplayed_cards.extend([Card(rank, suit) for suit in suits] * remaining)
    
    # 2. 从 unplayed_cards 中移除自己的手牌
    my_hand = state.hands[player]
    for card in my_hand:
        unplayed_cards.remove(card)
    
    # 3. 随机分配给其他3家
    random.shuffle(unplayed_cards)
    new_state = copy.deepcopy(state)
    idx = 0
    for p in [0, 1, 2, 3]:
        if p == player:
            continue
        hand_size = state.hand_size(p)
        new_state.hands[p] = unplayed_cards[idx:idx+hand_size]
        idx += hand_size
    
    return new_state
```

### UCB1 选择

```python
def ucb1_score(node: MCTSNode, parent_visits: int, c: float = 1.41) -> float:
    if node.visits == 0:
        return float('inf')  # 未访问节点优先
    exploit = node.wins / node.visits
    explore = c * sqrt(log(parent_visits) / node.visits)
    return exploit + explore

def select(root: MCTSNode) -> MCTSNode:
    node = root
    while not node.is_terminal():
        if not node.is_fully_expanded():
            return node
        # 选择 UCB1 最大的子节点
        node = max(node.children, key=lambda c: ucb1_score(c, node.visits))
    return node
```

### Expansion 扩展

```python
def expand(node: MCTSNode) -> MCTSNode:
    """从 untried_actions 中选一个，创建新子节点。"""
    if not node.untried_actions:
        return node  # 已完全展开
    
    action = node.untried_actions.pop()
    
    # 应用动作，生成新状态
    new_state = copy.deepcopy(node.state)
    if action is None:
        pass_turn(new_state, node.player)
    else:
        play_pattern(new_state, node.player, action)
    
    child = MCTSNode(
        state=new_state,
        player=new_state.current_player(),
        parent=node,
        action=action,
    )
    
    # 初始化 child.untried_actions
    child.untried_actions = get_legal_actions(new_state, child.player)
    
    node.children.append(child)
    return child
```

### Simulation 模拟

```python
def simulate(node: MCTSNode) -> float:
    """从 node 开始快速玩到游戏结束，返回结果。
    
    返回值：从 root.player 视角的胜率（0.0 - 1.0）
    """
    sim_state = copy.deepcopy(node.state)
    
    # 用档 1 策略快速玩到结束
    rollout_strategy = IntermediateStrategy()
    
    while not sim_state.finished:
        player = sim_state.current_player()
        pattern = rollout_strategy.select_pattern(sim_state, player)
        
        if pattern is None:
            pass_turn(sim_state, player)
        else:
            play_pattern(sim_state, player, pattern)
    
    # 评估结果
    return evaluate_result(sim_state, root_player)

def evaluate_result(state: GameState, root_player: int) -> float:
    """评估终局结果（从 root_player 视角）。
    
    返回 0.0 ~ 1.0：
    - 1.0 = 队友头游
    - 0.5 = 平局（头游+末游）
    - 0.0 = 对方头游
    """
    finish_order = state.finish_order
    first_player = finish_order[0]
    
    if is_teammate(first_player, root_player):
        # 我方头游
        if first_player == root_player:
            return 1.0  # 自己头游最好
        else:
            return 0.9  # 队友头游次之
    else:
        # 对方头游
        return 0.0
```

### Backpropagation 回传

```python
def backpropagate(node: MCTSNode, result: float):
    """将结果回传到路径上所有节点。"""
    while node is not None:
        node.visits += 1
        node.wins += result
        node = node.parent
```

## 实现步骤

### 步骤 1：创建 MCTS 模块结构

**文件**：
- `src/guandan/ai/mcts/__init__.py`
- `src/guandan/ai/mcts/node.py`
- `src/guandan/ai/mcts/determinize.py`
- `src/guandan/ai/mcts/search.py`

### 步骤 2：实现确定化逻辑

**文件**：`src/guandan/ai/mcts/determinize.py`

功能：
- `determinize(state: GameState, player: int) -> GameState`
- 根据已出牌推断未出牌
- 随机分配给其他3家

### 步骤 3：实现 MCTSNode 数据结构

**文件**：`src/guandan/ai/mcts/node.py`

功能：
- 节点数据结构
- `is_terminal()` - 判断是否终局
- `is_fully_expanded()` - 判断是否已展开所有子节点
- `get_legal_actions()` - 获取合法动作列表

### 步骤 4：实现 MCTS 主循环

**文件**：`src/guandan/ai/mcts/search.py`

功能：
- `mcts_search(root: MCTSNode, iterations: int) -> MCTSNode`
- Selection（UCB1）
- Expansion
- Simulation（用档1策略）
- Backpropagation

### 步骤 5：实现 ProfessionalStrategy

**文件**：`src/guandan/ai/strategies/professional.py`

功能：
- 实现 `AIStrategy` 接口
- 调用 MCTS 搜索
- 返回最佳行动

### 步骤 6：注册到工厂

**文件**：`src/guandan/ai/strategy.py`

修改：
```python
_STRATEGIES: Dict[int, str] = {
    0: "guandan.ai.strategies.novice.NoviceStrategy",
    1: "guandan.ai.strategies.intermediate.IntermediateStrategy",
    2: "guandan.ai.strategies.advanced.AdvancedStrategy",
    3: "guandan.ai.strategies.professional.ProfessionalStrategy",  # 新增
}
```

### 步骤 7：编写测试

**文件**：`tests/test_mcts.py`

测试：
- 确定化正确性（手牌数守恒、已出牌不重复）
- UCB1 计算
- MCTS 能收敛到合理决策
- ProfessionalStrategy 集成测试

### 步骤 8：调优参数

参数：
- `NUM_ITERATIONS` = 100 ~ 500
- `UCB_C` = 1.41
- `MAX_DEPTH` = 5 ~ 10
- Rollout 策略：档 1 或档 2

## 性能考虑

### 时间复杂度

**每次决策**：
- 确定化：O(未出牌数)，约 O(50-80) = O(1)
- MCTS 迭代：O(iterations × depth × branching_factor)
  - iterations = 100-500
  - depth ≈ 5-10
  - branching_factor ≈ 5-20（剪枝后）
- 总计：约 0.5-2 秒/决策（可接受）

### 优化方向

1. **剪枝**：
   - 只考虑 top-5 候选（利用 `enumerate_candidate_plays`）
   - 过滤明显劣势行动

2. **缓存**：
   - 状态哈希（避免重复计算）
   - 转置表（Transposition Table）

3. **并行**：
   - 未来可用多线程并行多个确定化

4. **渐进深化**：
   - 时间用完前尽量多搜索，用完立即返回

## 测试策略

### 单元测试

1. **确定化测试**：
   - 手牌数守恒
   - 已出牌不重复
   - 随机性（多次确定化结果不同）

2. **UCB1 测试**：
   - 未访问节点返回 inf
   - 高胜率节点优先
   - 低访问节点有探索奖励

3. **MCTS 循环测试**：
   - 能运行完整的 selection → expansion → simulation → backpropagation
   - 访问次数正确累加
   - 胜率正确更新

### 集成测试

1. **对战测试**：
   - 档3 vs 档2：档3 应有更高胜率
   - 档3 vs 档0：档3 应完胜

2. **性能测试**：
   - 每步决策时间 < 2 秒
   - 完整对局时间可接受

3. **冒烟测试**：
   - 5局对战无崩溃
   - 决策合理性（不出明显愚蠢的牌）

## 配置参数

**可配置参数**（未来可移到 config 或 profiles）：

```python
MCTS_CONFIG = {
    "iterations": 200,           # MCTS 迭代次数
    "ucb_c": 1.41,               # UCB1 探索常数
    "max_depth": 10,             # 最大搜索深度
    "rollout_strategy": 1,       # Simulation 用档 1 策略
    "num_determinizations": 1,   # 确定化次数（M3 用 1，M4 可提升）
    "top_actions": 5,            # 每个节点考虑的候选动作数
}
```

## 风险与缓解

### 风险 1：计算时间过长

**缓解**：
- 设置迭代次数上限（100-500）
- 添加时间限制（1-2秒）
- 优先实现，性能不足再优化

### 风险 2：确定化偏差

**问题**：单次确定化可能不准确

**缓解**：
- M3 先用单次，快速上线
- M4 可升级为多次确定化平均

### 风险 3：状态空间爆炸

**缓解**：
- 智能剪枝（top-N 候选）
- 深度限制
- Simulation 用快速策略

### 风险 4：Rollout 策略太弱

**问题**：纯随机 rollout 评估不准

**缓解**：
- 用档 1（进阶）策略做 rollout
- 或混合：档 1 + 少量随机性

## 验收标准

### 功能标准

- ✅ ProfessionalStrategy 实现 `AIStrategy` 接口
- ✅ `make_strategy(3)` 返回档3实例
- ✅ TUI 难度选择屏档3可进入游戏
- ✅ CLI `--difficulty 3` 可运行

### 质量标准

- ✅ 151+ 个测试全部通过
- ✅ 新增 15+ 个 MCTS 测试
- ✅ ruff/mypy 静态检查通过
- ✅ 对战档3 vs 档2，档3 胜率 > 60%

### 性能标准

- ✅ 每步决策时间 < 2 秒（平均）
- ✅ 完整对局时间可接受（< 5 分钟）
- ✅ 无明显卡顿或崩溃

## 文档更新

### 需要更新的文件

1. **README.md**：
   - 路线图勾选 M3
   - 更新 AI 档位说明

2. **CHANGELOG.md**：
   - 添加 v0.4.0 条目（M3 完成）

3. **docs/adr/**：
   - 新增 ADR-0002: IS-MCTS 算法选型

## 下一步（M4）

M3 完成后，M4 将在此基础上：
- 多次确定化平均
- 风格化参数（炸弹吝啬、控场节奏）
- 加载 profiles/*.json 配置

## 总结

M3 实现**简化版 IS-MCTS**：
- 单次确定化
- 100-500 迭代
- 智能剪枝
- 档1策略 rollout
- 目标：2秒内决策，胜率超过档2

这个方案在性能和质量之间取得平衡，适合单机游戏场景。

# ADR-0002: IS-MCTS 算法选型

## 状态
已采纳（2026-06-05）

## 背景

M3 阶段需要实现档 3"职业"AI，要求比档 2（高手）更强。档 0/1/2 都是基于启发式的策略：
- 档 0：纯贪心 + 概率过牌
- 档 1：top-5 候选 + 估值排序
- 档 2：估值 + 协作分 + 记牌

这些策略只考虑当前一步的得失，无法前瞻多步。要实现更强的 AI，需要引入搜索算法。

掼蛋游戏的特点：
- **不完全信息游戏**：玩家无法看到其他玩家的手牌
- **4 人固定搭档**：需要协作意识
- **复杂的行动空间**：每回合可能有多种出牌选择
- **确定性规则**：给定状态和行动，下一状态唯一

## 决策

采用 **IS-MCTS（Information Set Monte Carlo Tree Search）** 算法。

### 算法选型对比

| 算法 | 优点 | 缺点 | 是否采用 |
| --- | --- | --- | --- |
| **Minimax + Alpha-Beta** | 经典博弈树搜索，适合完全信息游戏 | 不适合不完全信息游戏，无法处理隐藏信息 | ❌ |
| **CFR (Counterfactual Regret Minimization)** | 适合不完全信息游戏，理论保证强 | 计算量大，需要离线训练，实现复杂 | ❌ |
| **IS-MCTS** | 适合不完全信息游戏，在线搜索，实现相对简单 | 需要多次确定化才能稳定，单次结果有偏差 | ✅ |
| **Deep RL (强化学习)** | 可以学习复杂策略 | 需要大量训练数据和计算资源，不适合单机游戏 | ❌ |

### IS-MCTS 原理

**核心思想**：在不完全信息游戏中，通过"确定化"将隐藏信息随机化，然后在确定化的世界中运行标准 MCTS。

**算法流程**：
1. **Determinization（确定化）**：
   - 根据已知信息（自己手牌、已出牌），推断其他玩家可能的手牌
   - 将未出牌随机分配给其他 3 家
   
2. **MCTS 搜索**：在确定化的世界中运行标准 MCTS
   - **Selection**：用 UCB1 从根节点选择最优路径到叶子节点
   - **Expansion**：扩展一个新子节点
   - **Simulation（Rollout）**：用快速策略玩到游戏结束
   - **Backpropagation**：将结果回传更新所有节点

3. **决策**：返回访问次数最多的子节点对应的行动

### 简化版设计（M3）

考虑到单机游戏场景和计算资源限制，M3 实现**简化版 IS-MCTS**：

1. **单次确定化**：每次决策只做 1 次确定化（不是多次平均）
   - 理由：计算更快，对单机游戏体验足够
   - 未来可通过参数调整确定化次数

2. **浅层搜索**：限制搜索深度和迭代次数
   - 迭代次数：200（可调）
   - 候选动作剪枝：只考虑 top-5

3. **智能剪枝**：
   - 利用现有的 `enumerate_candidate_plays` 获取 top-N 候选
   - 过滤明显劣势的行动

4. **快速 Rollout**：
   - Simulation 阶段用档 1（进阶）策略，不用随机
   - 理由：纯随机太弱，影响评估质量

### UCB1 公式

```
UCB1(node) = win_rate + C * sqrt(ln(parent_visits) / node_visits)
```

- `win_rate`：该节点的平均胜率（exploitation，利用）
- 右侧：exploration bonus（探索奖励）
- `C`：探索常数（默认 1.41，即 sqrt(2)）

### 参数配置

```python
MCTS_CONFIG = {
    "iterations": 200,           # MCTS 迭代次数
    "ucb_c": 1.41,               # UCB1 探索常数
    "max_depth": 10,             # 最大搜索深度（预留）
    "rollout_strategy": 1,       # Simulation 用档 1 策略
    "top_actions": 5,            # 每个节点考虑的候选动作数
}
```

## 后果

### 优点

✅ **前瞻能力**：能够前瞻多步，做出更优决策
✅ **适合不完全信息**：通过确定化处理隐藏信息
✅ **在线搜索**：无需预训练，即时决策
✅ **可扩展**：未来可增加确定化次数、迭代次数

### 缺点

❌ **计算开销**：每步决策需要 0.5-2 秒（200 迭代）
❌ **确定化偏差**：单次确定化可能不准确
❌ **状态空间大**：需要剪枝控制复杂度

### 缓解措施

- **性能优化**：智能剪枝（top-5 候选）、深度限制
- **确定化偏差**：M4 可升级为多次确定化平均
- **用户体验**：2 秒决策时间对单机游戏可接受

## 实现

模块结构：
```
src/guandan/ai/mcts/
├── __init__.py           # 导出和配置
├── node.py               # MCTSNode 数据结构
├── determinize.py        # 信息集确定化
└── search.py             # MCTS 主循环
```

策略类：
```python
class ProfessionalStrategy:
    name = "职业"
    difficulty = 3
    
    def select_pattern(self, state, player):
        # 1. 确定化
        det_state = determinize(state, player, rng)
        # 2. MCTS 搜索
        root = MCTSNode(state=det_state, player=player)
        best_child = mcts_search(root, iterations=200)
        # 3. 返回最佳行动
        return best_child.action if best_child else None
```

## 参考资料

- Browne et al. (2012): "A Survey of Monte Carlo Tree Search Methods"
- Long et al. (2010): "Understanding the Success of Perfect Information Monte Carlo Sampling in Game Tree Search"
- Cowling et al. (2012): "Information Set Monte Carlo Tree Search"

## 未来改进（M4）

- 多次确定化平均（提升稳定性）
- 并行 MCTS（多线程加速）
- 转置表缓存（避免重复计算）
- 渐进深化（时间限制内尽量多搜索）

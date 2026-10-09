# 轻量动作排序研究（v8）

职业（3）和戴长胜（4）加入默认关闭的 `action_ranker`。模型只提名根候选，最终选牌仍由共同暗牌世界评估与现有收益保护决定。前三档、五档编号、存档和 `select_pattern` 接口不变。

本轮已完成实现、训练、消融及开发对赛。**两档都未通过开发门槛，保持默认关闭。** 动作诊断有所改善，但整队与混合搭档收益没有同时为正，因此没有使用独立验收种子，也没有启动 48 对完整比赛。

## 实现与信息边界

`src/guandan/ai/action_ranker.py` 提供 `score_actions(observation, actions)`，运行时仅加载 JSON 线性权重。输入是不可变的行动者观察对象：自身手牌、公开张数、桌顶及所有权、已出和公开归属牌、名次、双方级别与 A 失败次数；不保留真实暗牌、发牌种子、历史对象或未来事件。其他玩家手牌及私有种子替换测试覆盖四个座位和 2/9/A 级。

520 个特征包含牌型、出牌张数与强度、实体花色、逢人配消耗、出牌前后对子/三张/炸弹与自然同花连接，以及公开战术状态的交互。特征提取仅用计数器，不对每个动作做递归手牌规划。输出是相对排序分数，不是胜率。

两档仅在根搜索中评分一次。最多替换末尾一个未受保护的普通候选，候选数不增加；战术参考、最低合法回应、过牌、一手出完和既有炸弹保留。若最优推荐已经在池内，则不替换。续局策略、估值权重、搜索门槛、收益保护及残局路径保留原实现。模型阶段使用当前根预算的至多 5%；准备或评分超时、缺失、不兼容、非有限数均原子回退完整候选池。关闭开关时不读模型，不额外消费随机数。

模型兼容性检查包括规则版本、特征版本与顺序、系数维度/有限性，以及标签使用的整场估值 SHA-256。训练依赖 NumPy，仅位于可选的 `ai-training` extra；游戏运行时没有机器学习依赖。

## 冻结对照与数据

训练和对照均使用接入前的**当前工作区默认策略**，包括已有但默认关闭的协作研究代码。完整冻结源码及配置位于 `benchmarks/ai-v8-baseline-snapshot.zip`，标签进程从独立目录导入并校验指纹；对赛使用独立 Python 进程执行冻结策略。

- 源码/配置指纹：`d2082d68aef3264d88d16d64e0cbcd233eb8ce349e2d1ae99afd87b4373802de`。
- 整场估值指纹：`d1c027cb92afd356f7c6c2d2da8b06bf5f7a3755c25e28d6c2c54512bc51461c`。
- Git 基点：`77190bf5f831f4f0c6350e39ab9cd49981f14d35`；源码指纹同时覆盖该基点之外的工作区改动。

固定 576 副新牌按整副划分为训练 384、调参 96、动作诊断 96。按开局、中盘、头游已定/残局轮流选取**每副一处**局面，符合“每副最多三处”的上限；无法取得目标阶段时记录实际阶段。级别包括不对称级别与冲 A，覆盖 A 失败计数和公开贡还牌。

每处最多 16 个动作，纳入现有职业/最高档根候选，再按牌型均衡补入合法动作。每个动作共享 32 个假设暗牌世界，各配新手、进阶、高手搭档；本家后续及对手均执行冻结高手策略。完整结算名次后，映射到冻结整场继续值。不以让牌或抢头游次数为目标。原始压缩标签保存公开快照、动作、三个搭档各 32 个完整续局收益及来源种子；来源种子仅作数据溯源，不进入观察对象或特征。

采集端缓存确定性策略决策和完整续局后缀。首副牌三处局面的全部标签与未缓存版本逐项一致；另有跨级别、搭档的缓存一致性测试。该缓存只用于离线标签采集，不改游戏续局策略。

成对 logistic 排序以同一世界中的收益差构造软标签，先在三个搭档间平均，再以 32 个世界估计误差，避免将相关搭档当作 96 个独立样本。固定 160 次全批梯度更新，L2 只从 `{0.001, 0.01, 0.1}` 中按调参 regret 选择。动作诊断比较模型推荐与冻结快速战术参考在同一已标注动作池内的 regret；它不是所有合法动作的精确最优收益。

## 预定实验与启用门槛

每档先进行整队 32 对、混合搭档 32 对开发对赛（128 次固定工作量）。只有两项平均收益差均为正、独立动作诊断 regret 下降及预算检查通过，才锁定候选并进入独立验收。

独立验收每档固定整队 240 对、混合搭档 240 对，使用职业 256 / 最高档 768 次工作量；另做 48 对实际完整比赛。所有发牌种子按阶段、比赛编号与局号 SHA-256 派生，完整比赛不用相邻 `seed + 局号`，避免不同比赛牌序重叠。样本规模在运行前固定，观察结果后不追加样本。开发失败的档位保留独立种子，不运行验收。

生产时钟检查串行覆盖热缓存、冷缓存及一名模拟真人行动后的三家连续行动。逐次检查模型阶段 5% 上限和端到端 `1.15 × 预算 + 100ms`。固定工作量强度与生产时钟数据分开解释。

默认启用必须同时满足：整队及混合收益差的 95% 配对区间下界均大于零；三个搭档分项平均差均非负；48 对实际整场胜率的 95% 配对区间下界大于 50%；合法、完成、事件重放及延迟检查通过。当前开关保持关闭。混合代理只是执行风格代理，真人收益仍需真人对局验证。

## 复现

```bash
uv sync --locked --extra dev --extra gui --extra packaging --extra ai-training
unzip benchmarks/ai-v8-baseline-snapshot.zip -d /tmp/guandan-v8-baseline
.venv/bin/python -m scripts.fit_action_ranker --stage collect \
  --baseline-root /tmp/guandan-v8-baseline --workers 8
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m scripts.fit_action_ranker --stage fit
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m scripts.ablate_action_ranker
.venv/bin/python -m scripts.ai_action_ranker_validation --stage clock \
  --baseline-root /tmp/guandan-v8-baseline --workers 1
.venv/bin/python -m scripts.ai_action_ranker_validation --stage dev \
  --baseline-root /tmp/guandan-v8-baseline --workers 8
.venv/bin/python -m scripts.ai_action_ranker_validation --stage validation \
  --baseline-root /tmp/guandan-v8-baseline --workers 8
.venv/bin/python -m scripts.ai_action_ranker_validation --stage full \
  --baseline-root /tmp/guandan-v8-baseline --workers 8
.venv/bin/python -m scripts.ai_action_ranker_validation --stage replay \
  --baseline-root /tmp/guandan-v8-baseline
.venv/bin/python -m scripts.ai_action_ranker_validation --stage report \
  --baseline-root /tmp/guandan-v8-baseline
```

采集和对赛均支持相同配方下的断点续跑。源码、模型或配方改变后使用新的输出目录；开发锁定之后拒绝不同源码。原始标签、拟合、时钟、各对赛报告和最终门禁均位于 `benchmarks/action-ranker-v1/`。

消融分别去除公开状态交互、出牌花色计数和剩余手牌结构，在原训练集上重拟合，固定使用主模型由调参集选定的 L2。仅报告动作诊断，不据此重新选择模型或改变验收样本。

## 本轮结果

正式采集为 576 副、576 处局面、5,492 个动作、527,232 条完整续局收益；训练/调参/诊断为 384/96/96 副。实际开局/中盘/头游已定或残局为 194/209/173 处，其中 86 处头游已定、387 处级别不对称，本家/对手第三次冲 A 为 61/66 处。原始数据见 `benchmarks/action-ranker-v1/labels/`，[数据审计](../benchmarks/action-ranker-v1/dataset-audit.json)检查了维度、有限性、公开快照和来源划分。

模型由调参集选择 L2=0.001，21,219 个训练动作对，520 个系数。权重为 `src/guandan/ai/profiles/action_ranker_v1.json`（32 KB），SHA-256 为 `f32b49470b2a969f7e33f4d8550ea36f2fda4ba5f52e895e3cfbecb3c9a14cc8`。冻结候选代码为 `benchmarks/ai-v8-experimental-snapshot.zip`。

| 调参模型 | 平均 regret |
| --- | ---: |
| 冻结快速战术参考 | 0.021644 |
| L2=0.001 | 0.031071 |
| L2=0.01 | 0.034737 |
| L2=0.1 | 0.039147 |

| 独立动作诊断（96 副） | 平均 regret |
| --- | ---: |
| 冻结快速战术参考 | 0.032387 |
| 主模型 | 0.028293 |
| 去掉公开状态交互后重拟合 | 0.033778 |
| 去掉出牌花色计数后重拟合 | 0.030285 |
| 去掉剩余结构后重拟合 | 0.039841 |

主模型在动作诊断中比快速参考下降约 12.6%，但在调参集上仍落后于快速参考。因此不能仅凭排序指标宣称棋力提升；消融也只解释这一组诊断样本。完整记录见[拟合](../benchmarks/action-ranker-v1/fit.json)与[消融](../benchmarks/action-ranker-v1/ablation.json)。

903 项测试全部通过，覆盖率 84.90%；Ruff、mypy（93 个源文件）和存档/会话/事件重放覆盖率门槛均通过。30 个默认固定决策的动作与原因与 v7 基线相同。另在不对称级别、第三次冲 A 状态进行四组关闭模型的质量对照，完整名次一致，配对收益差均为零，见 `off-control-3.json` / `off-control-4.json`。这些对照不用于棋力推断。

[串行生产时钟](../benchmarks/action-ranker-v1/clock.json)的 42 次决策全部通过。模型阶段最长职业 27.24ms、最高档 27.04ms，均在当次预算 5% 内；端到端最长为 1.298 / 2.006 秒，均满足各自当次预算的软容差。默认时限未增加。

本机 NumPy 2.2.6 的 Accelerate 后端产生了矩阵乘法浮点警告，类似现象已有 [NumPy 问题记录](https://github.com/numpy/numpy/issues/29820)。本轮独立用非 BLAS 的 `einsum` 重算全部 160 次主模型更新，最大系数差为 5.55×10⁻¹⁷；576 处的 NumPy 与实际 `score_actions` API 评分最大差为 7.77×10⁻¹⁶，推荐动作全部一致。没有忽略真实非有限数，详见[数值复核](../benchmarks/action-ranker-v1/numerical-verification.json)。

开发对赛采用两档各整队 32 对、混合 32 对、128 次固定工作量，共 128 对、256 个小局，全部完成并逐局通过严格事件重放。以下区间属于开发样本，不能替代独立验收。

| 档位 | 开发对赛 | 平均配对收益差 | 95% 配对区间 | 模型提名次数 |
| --- | --- | ---: | --- | ---: |
| 职业 | [整队](../benchmarks/action-ranker-v1/dev-team-3.json) | 0.000000 | [0.000000, 0.000000] | 150 |
| 职业 | [混合搭档](../benchmarks/action-ranker-v1/dev-mixed-3.json) | −0.009706 | [−0.021008, −0.000497] | 75 |
| 戴长胜 | [整队](../benchmarks/action-ranker-v1/dev-team-4.json) | −0.015584 | [−0.057466, +0.011052] | 97 |
| 戴长胜 | [混合搭档](../benchmarks/action-ranker-v1/dev-mixed-4.json) | 0.000000 | [0.000000, 0.000000] | 41 |

新手/进阶/高手搭档分项平均收益差，职业为 −0.010073 / −0.012178 / −0.006900；戴长胜三项均为零。363 次候选提名没有形成同时改善两类对赛的结果；零差表示完整结算收益一致，不意味着搜索过程完全一致。

两档的开发门禁均失败，独立整队 240 对、混合 240 对与实际完整比赛 48 对均**未运行**，没有在观察失败后扩样。[锁定记录](../benchmarks/action-ranker-v1/validation-lock.json)保留候选/对照/权重指纹和全部预定规模；[最终门禁](../benchmarks/action-ranker-v1/validation.json)明确记录 `not_run_development_failed`、`eligible_for_default=false`。因此本轮没有实际整场胜率结论。

[职业真人公开前缀诊断](../benchmarks/action-ranker-v1/replay-3.json)与[最高档诊断](../benchmarks/action-ranker-v1/replay-4.json)各六处、三个搭档代理、32 个共同世界、两条根动作分支，合计 2,304 条合法分支全部完成。两档六处实际选牌均与冻结对照一致，代理收益差为零。原真人记录为第 2 版规则，本轮明确投影到第 3 版规则；后续执行为冻结高手及搭档代理，不能解释为真实人机收益。

本轮表明轻量特征和计时接入可行，排序指标改善不足以证明根候选补充能提升实战。若继续研究，应先诊断模型提名为何在现有收益保护与模拟续局下未产生稳定增益，使用新的预定数据/实验版本；本轮权重、原始标签及失败记录全部保留。

## 方法来源

[DanZero+](https://arxiv.org/html/2312.02561v1) 使用学习模型筛选动作，支持本轮候选补充方向；线性模型在本项目预算下的效果仍由上述实验检验。[OpenGuanDan](https://arxiv.org/html/2602.00676v1) 分别评测 AI 对赛与人机表现，因此混合代理结果不直接解释为真人收益。

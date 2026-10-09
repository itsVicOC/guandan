# 规划性能优化 v10

最终核为生产 `hand_plan.py` 的单层 8192 项缓存版本，SHA-256 为 `65b767201b7b5c1843c50e4bc40b674a5ae9c2c43f937db2c492fa4edc88fcf3`。

- `quality.json`、`workspace-coverage.json`、`workspace-regression.json`：正式工作区质量记录，933 项通过、84.87% 覆盖；后续八对复核的 935 项质量记录在 `../budget-refinement-v11/`。
- `equivalence.json`：576 副旧标签中的 11,272 个实际生产估值与冻结计数器完全相等。`tests/hand_plan_reference.py` 是比较基准。
- `serial-planner.json`：729 个冷缓存调用串行交替比较。原型与生产规划核仅相差局部变量类型注解，执行逻辑相同。
- `counter-clock.json`、`packed-clock.json`、`packed-refined-clock.json`：原先未设八对上限的 v9/v10 冻结实现，各 42 次串行时钟；使用相应 `source-snapshot.zip` / v9 候选快照复现。
- `clock-action-diagnostic.json`：所有改变的默认时钟动作（一个）在 32 个共同世界、三档搭档下的 192 条完整代理分支；三个分项均为负，不能以计算效率宣称对赛收益。
- `off-control.json`：四对完整名次质量对照，收益差为零，不作为强度样本。
- `origin.json`、`default-regression.json`、`coverage.json`：中间版本的研究记录。初期隔离导入使覆盖报告同时计入两份路径，覆盖门槛未通过；正式质量以工作区重跑的 `workspace-coverage.json` 为准。原型曾复制双层缓存，最终修复为单层，并增加清缓存必须重新计算的检查。

`source-snapshot.zip` 记录规划优化完成、高手复核尚未设八对上限的源码；当前八对源码位于 v11 候选快照。各记录均保留自身源码/配方指纹，不能混合版本计算时钟或强度。

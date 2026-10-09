# 项目审查建议落地（2026-10-09）

对应 [整体审查](REVIEW-2026-10-09.md) 的六项执行顺序。本轮在已有 v7～v12 研究工作区上实施，保留原始研究代码与数据；没有改变默认实验开关。本文记录发布前的本地验收，发布版本为 `v0.8.7-beta.1`。

| 审查项 | 已落实的改动 | 验证证据 |
| --- | --- | --- |
| 1. 跨局 A 次数与恢复 | 引擎共用 `deal_next_round`、`set_dealt_round_starter`，前端会话与整场基准统一调用；通过 `replace` 更新先手并保留发牌全部字段。对受影响的第 3 版、后续局存档，仅在唯一初始计数组合能通过完整严格重放和快照校验时修复，先备份原始 JSON，再增加修订号。其他损坏仍拒绝恢复。 | `tests/test_round_recovery.py`：14 项，真实贡还/抗贡、待确认时保存恢复、继续出牌与结算、三次失败退 2、规则 1/2，以及损坏负例。 |
| 2. 当前生产基线 | CI 指向 `benchmarks/production/ai-regression.json`；兼容性 schema 2 使用生产语义指纹，默认关闭的研究项不影响兼容性，报告仍保存完整配置及指纹。 | [基线审阅](benchmarks/production/baseline-review.json)：30 个动作与原因相同；[当前门禁](benchmarks/production/ai-regression-check.json)通过。 |
| 3. 共享会话与可移植 CI | benchmark-gate 增加真实会话多局恢复验证；研究 job 安装 `ai-training`；历史 worker 从版本化 v11 夹具解压到临时目录并验证原始源码指纹。 | 全量测试无跳过；[隔离旧策略对照](benchmarks/production/default-policy-parity.json)30 个案例的动作、原因、RNG 状态全部一致；[整场冒烟](benchmarks/production/full-match.json)8 局完成、7 局含贡还牌，事件流逐局重放。 |
| 4. RPC、manifest、配置与预算 | 两个评测入口共用 RPC；启动、请求、写管道有时限，stderr 写文件，terminate/kill 兜底，故障保留请求、阶段和校验和并终止评测。manifest 覆盖规则、序列化、策略、脚本、夹具和锁文件，配方变更拒绝复用。`SearchConfig`/`ResearchConfig` 保留旧接口；各阶段共用绝对预算，残局求解器使用 70%，回退使用完整决策剩余时间。 | RPC 九种故障路径测试、manifest 依赖变更测试、类型配置/旧接口动作与 RNG 对照、残局预算继承测试；Ruff、mypy 通过。 |
| 5. 前端生命周期与后台 I/O | GUI/TUI 共用 `TurnController` 的空闲、思考、保存、失败、离开转换；保存失败按存储阶段重试，不重复出牌。存档页、恢复副本、历史页、回放验证、新局冲突检查及覆盖改用后台工作；代际门禁丢弃离开/隐藏页面的过时回调，Qt 关闭后不再向已销毁对象发信号。 | 慢读取期间返回仍响应、后台错误发生在页面离开后不弹窗/导航、重试与离开状态测试；30 个 GUI/TUI 图像冒烟产物通过。 |
| 6. 单项 AI 诊断与研究归档 | `ActorObservation` 统一战术、搭档证据与排序的公开信息边界；诊断增加完整共同世界、截断/丢弃比例、配对标准误、缓存和可选峰值内存。实际运行只改变续局长度的探索性诊断。研究索引逐文件 SHA-256，可导出并再次校验研究附件，原始失败结果保留。 | [单项诊断](benchmarks/review-diagnostic-20261009/single-horizon-diagnostic.json)、[内存诊断](benchmarks/review-diagnostic-20261009/memory-diagnostic.json)、[验收协议](benchmarks/review-diagnostic-20261009/protocol.json)、[数据索引](benchmarks/research-index.json)。 |

## AI 诊断结果与启用判断

16 个已观察标签局面、两档、两种续局长度，共 64 次固定工作量决策，每次 64 次动作评估；使用新的诊断种子，同一局面的两个方案共享随机流。它是损失机制诊断，不是独立胜率验收。

| 档位 | 40 手续局完成比例 | 120 手续局完成比例 | 最终动作平均 regret：40 → 120 | 原始搜索平均 regret：40 → 120 |
| --- | ---: | ---: | ---: | ---: |
| 职业 | 37.11% | 100% | 0.011978 → 0.008231 | 0.016299 → 0.027667 |
| 戴长胜 | 25.12% | 100% | 0.012837 → 0.013567 | 0.015187 → 0.027845 |

延长续局提高了完成比例，但原始搜索动作的损失增大，最高档最终动作也略差。候选覆盖、续局偏差和收益保护应分别评估；不能依据模拟完成率直接启用新策略。本轮不追加独立验收样本，默认研究开关继续关闭。协议明确了后续冻结、整队、混合搭档、实际整场、时钟与质量的启用门槛。

2 个局面的内存测量启用了 `tracemalloc`，记录 Python 分配峰值与缓存差值；这些耗时受插桩影响，不作为生产延迟证据，也不代表进程全部内存。

## 验收

- 全量 pytest：**1,052 项通过，无跳过**；分支覆盖率 **85.07%**。
- 恢复边界覆盖率：storage **85.37%**、session **81.87%**、replay **76.12%**，均达到现有门槛。
- Ruff、mypy（100 个源码文件）、差异空白检查通过。
- 当前固定门禁 30/30；隔离 v11 对照的动作、原因、RNG 状态 30/30 一致。
- 8 局整场冒烟完成并通过事件重放；30 个 offscreen GUI/TUI 图像产物通过，历史空态画面已检查。
- 默认生产预算串行检查 **42/42 通过**，每档包括 6 个暖缓存、12 个逐局清理缓存局面，以及三家连续行动；记录 AI 计算与 RPC 等待两个口径。
- 实际前端调度与本地自动保存的单局面测量：职业 GUI/TUI 连续三家为 **5.15 / 3.63 秒**，戴长胜为 **8.02 / 6.59 秒**，均提交三次自动保存并回到真人回合。包含 GUI 的 650ms 展示停留、TUI 首次 300ms/后续 100ms 停留；使用 offscreen/headless 测试事件循环，不代表所有牌局或前台桌面性能。
- 研究附件导出并逐文件校验 **892 个文件、124,075,761 原始字节**；原始数据与失败实验继续保留，附件为 `benchmarks/archives/research-20261009.zip`。

串行预算、连续三家实际前端等待和归档校验结果见 [质量摘要](benchmarks/production/quality.json)。测试与原始覆盖率日志位于 `/private/tmp/guandan-optimization-tests.log`、`/private/tmp/guandan-optimization-coverage.json`；关键数值已保留在质量摘要。

三个验收探针的完整源码与 SHA-256 保存在 [验证脚本](benchmarks/production/validation-harnesses.json) 中，从项目根目录运行即可复现。研究数据的 `index/verify/export` 命令见 [数据说明](benchmarks/README.md)。

本次环境为 macOS ARM64 / Python 3.10.20。上述本地验收完成时尚未远程执行 CI 或 Windows/Linux 打包；标签发布流程另行执行跨平台检查和构建，结果见 [GitHub Actions](https://github.com/itsVicOC/guandan/actions)。新策略尚未完成强度验收。兼容的旧同步调用入口保留供既有调用者使用；页面中的正常新局、读取、恢复和离开流程采用后台机制。

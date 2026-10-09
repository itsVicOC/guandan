# 短手牌封堵 v12b

职业与戴长胜均未通过预定开发筛选，默认 `urgent_blocking=false`。完整方法、边界与数值结果见 [研究说明](../../docs/ai-urgent-blocking.md)。

- [冻结配方](recipe.json)：源码、脚本指纹、种子命名空间、预算与预定样本量。
- [汇总与原始报告索引](summary.json)：256 对、512 局；每组原始文件保存所有决策及计时。
- [逐档启用结论](validation.json)：独立验收因开发失败而未运行，两档保持关闭。
- [对照快照](baseline-snapshot.zip)与[候选快照](candidate-snapshot.zip)：保留未提交源码，包含逐文件指纹。
- [质量检查](quality.json)、[完整测试日志](tests-final-coverage.log)、[覆盖率](coverage-final.json)。
- [关闭兼容回归](off-regression.json)与[信息边界](information-boundary.json)。
- [权重 6 时钟检查](clock-w6.json)与[权重 12 时钟检查](clock-w12.json)：冷/热缓存及三家连续行动。
- [职业公开前缀代理回放](replay-3.json)与[戴长胜公开前缀代理回放](replay-4.json)：各 1,152 条，不解释为真人胜率。

首次命名空间 `v12` 的 6 对数据因报告元数据错误取消，保存在 `cancelled-first-harness/`，不参与选择。正式 `v12b` 首组 32 对的 A 级统计字段后来从公开结算结果补齐；策略、工作进程、牌序和全部原始观察值未变。修复前的材料及指纹保留于 `pre-a-metadata-fix.zip`、`pre-dependency-verification-fix.zip` 和 [迁移审计](a-metadata-migration.json)。

正式候选源码从冻结起没有修改；后续测试加强了“过牌也会让对手出完、必须压牌”的状态与断言。当前测试文件随工作区交付，历史冻结测试保留在快照内。

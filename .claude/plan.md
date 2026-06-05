# 修复计划：项目配置问题修复

## 问题总结

经过全面检查，发现以下4个问题需要修复：

1. **ruff 静态检查报大量中文全角符号警告** - 835个 RUF002/RUF003 警告
2. **mypy 未安装** - pyproject.toml 声明但虚拟环境中缺失
3. **docs/rules.md 不存在** - README 中引用但文件不存在
4. **profiles 配置问题** - pyproject.toml 声明 `guandan.ai.profiles/*.json` 但目录不存在且代码无引用

## 问题分析

### 问题1：中文全角符号警告（835个）

**现状：**
- ruff 检查所有中文 docstring/comment 中的全角标点（：、（、）、，等）
- 这是 RUF002（docstring）和 RUF003（comment）规则
- 项目是中文项目，大量使用中文注释和文档字符串

**解决方案：**
在 `pyproject.toml` 的 `[tool.ruff.lint]` 中添加忽略规则：
```toml
ignore = ["E501", "RUF002", "RUF003"]
```

**理由：**
- 这是中文项目，中文标点符号是正常且符合习惯的
- 全角符号不影响代码功能
- 强制半角会让中文文本可读性变差

### 问题2：mypy 未安装

**现状：**
- pyproject.toml 在 dev 依赖中声明了 `mypy>=1.8`
- 虚拟环境中没有 mypy 命令
- 虚拟环境是 pip 创建的标准 venv（不是 uv）

**解决方案：**
重新安装开发依赖：
```bash
uv pip install -e ".[dev]"
```

**理由：**
- 系统已安装 uv（/Users/itsvic/.local/bin/uv）
- README 推荐使用 uv
- 使用 uv 可以更快地安装依赖

### 问题3：docs/rules.md 缺失

**现状：**
- README.md:51 引用 `[docs/rules.md](docs/rules.md)`
- 实际只有 `docs/adr/0001-event-flow.md`
- README 中已有规则摘要表格（牌数/玩家/级牌等）

**解决方案：**
创建 `docs/rules.md` 文档，包含：
1. 完整的掼蛋规则说明
2. 基于 README 的规则摘要扩展
3. 引用 CHANGELOG 中提到的《掼蛋的接风判定与四名次的产生规则》
4. 详细的牌型说明、升级规则、特殊规则（进贡/还贡/抗贡/漂牌/过A）

**内容来源：**
- README.md 的规则摘要
- CHANGELOG.md 中的规则修复说明（v0.1.2）
- engine/rules/ 目录下的实现

### 问题4：profiles 配置

**现状：**
- pyproject.toml:46 声明 `"guandan.ai.profiles" = ["*.json"]`
- `src/guandan/ai/profiles/` 目录不存在
- 代码中没有任何对 profiles 的引用（grep 无结果）
- CHANGELOG 提到"档 5 戴长胜 AI"是 M4 阶段

**解决方案选项：**

**方案A：创建占位目录**
- 创建 `src/guandan/ai/profiles/` 目录
- 添加 `.gitkeep` 或 `README.md` 说明这是为 M4 准备的
- 保留 pyproject.toml 配置

**方案B：移除配置**
- 从 pyproject.toml 删除 `[tool.setuptools.package-data]` 中的 profiles 配置
- M4 实现时再添加

**推荐方案A**，理由：
- profiles 是规划中的功能（M4 戴长胜 AI 风格化配置）
- 提前创建目录不会造成问题
- 保持 package-data 配置的前瞻性

## 实施步骤

### 步骤1：修复 ruff 配置
**文件：** `pyproject.toml`
**操作：** 在 `[tool.ruff.lint]` 的 `ignore` 列表中添加 `"RUF002", "RUF003"`

### 步骤2：重新安装开发依赖
**命令：** `uv pip install -e ".[dev]"`
**验证：** 运行 `mypy src` 确认安装成功

### 步骤3：创建 docs/rules.md
**文件：** `docs/rules.md`
**内容结构：**
```
# 掼蛋规则详解

## 1. 游戏概述
## 2. 基本规则
## 3. 牌型说明
## 4. 出牌规则
## 5. 升级规则
## 6. 特殊规则
   - 进贡/还贡/抗贡
   - 漂牌
   - 过A
   - 接风（借风）
## 7. 胜负判定
## 8. 参考资料
```

### 步骤4：创建 profiles 目录
**目录：** `src/guandan/ai/profiles/`
**文件：** `src/guandan/ai/profiles/README.md`
**内容：** 说明此目录用于 M4 阶段的 AI 风格配置文件

## 验证清单

- [ ] `ruff check src tests` 无 RUF002/RUF003 警告
- [ ] `mypy src` 可正常运行
- [ ] `docs/rules.md` 存在且内容完整
- [ ] `src/guandan/ai/profiles/` 目录存在
- [ ] 所有 151 个测试仍然通过

## 预期成果

1. **代码质量工具正常工作** - ruff 和 mypy 都能正常运行且无误报
2. **文档完整** - 用户可以查看完整规则文档
3. **配置一致** - pyproject.toml 的声明与实际文件结构一致
4. **为后续开发做好准备** - profiles 目录为 M4 阶段预留

## 风险评估

- **低风险：** 这些都是配置和文档修复，不涉及代码逻辑变更
- **无破坏性：** 测试套件应该全部通过
- **可回滚：** git 可以轻松回滚这些更改

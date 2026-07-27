# 掼蛋（Guandan）— 本地 GUI / TUI 单机版

> 状态：**v0.8.0-beta.6 / 公测版**（贡还牌流程与公开信息优化）
> 规则：与全国锦标赛通用口径一致
> AI：5 档（新手 / 进阶 / 高手 / 职业（团队感知 SO-ISMCTS）/ **戴长胜（自对弈调优）**）
> 持久化：Profile / Savegame / History / 断点续局恢复已实现
> 运行环境：Python 3.10+

## 特性

- 🎴 严格按全国掼蛋比赛规则：2 副牌 108 张、4 人固定搭档、级牌、4-10 张炸弹、同花顺、进贡/还贡、报牌、逢人配、抗贡、过 A
- 🤖 5 档 AI 难度；高档 AI 使用多隐藏世界采样、团队对抗搜索、过牌信念、分层候选和渐进扩展，最高档风格参数由镜像自对弈调优
- 🔁 历史战绩 / 自动保存 / 断点续局恢复 / GUI 与 TUI 牌桌式回放，跨局保留同一比赛标识
- 🖥️ 桌面 GUI（`PySide6`）：现代四人牌桌、单排重叠手牌、缩略牌墩、动态座位状态，以及大厅 / 难度 / 存档 / 历史 / 回放 / 规则完整流程
- 💻 终端 TUI（`textual`），首页 / 难度页 / 牌局页已统一深色牌桌风格，macOS / Linux 主流终端兼容
- 🧪 公测版已完成规则回归、AI 候选策略、AI 对战基准、GUI session、TUI 主流程与断点续局的自动化验证
- 🔒 GUI / TUI 并行运行时使用跨进程存储锁保护 Profile、存档和历史写入，避免并发写损坏与统计更新丢失

## 安装

### 直接运行桌面包

从 [GitHub Releases](https://github.com/itsVicOC/guandan/releases) 下载对应平台压缩包，解压后即可运行，无需安装 Python：

- Windows x64：运行 `Guandan/Guandan.exe`。
- macOS Apple Silicon / Intel：打开 `Guandan.app`。
- Linux x64：运行 `Guandan/Guandan`；若执行位丢失，先执行 `chmod +x Guandan/Guandan`。

当前测试包尚未进行商业代码签名。Windows SmartScreen 或 macOS Gatekeeper 首次启动时可能要求用户确认；macOS 可在 Finder 中右键应用并选择“打开”。

### Python 安装

```bash
# 推荐使用 uv
uv venv
uv pip install -e ".[dev,gui]"

# 或用 pip
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,gui]"
```

## 快速开始

```bash
# CLI 模式
python -m guandan.cli

# TUI 模式
guandan

# GUI 模式
guandan-gui
```

## 规则摘要

| 项 | 规则 |
| --- | --- |
| 牌数 | 2 副扑克 108 张 |
| 玩家 | 4 人，**东↔西 / 南↔北** 为同队 |
| 出牌方向 | 逆时针：**东 → 北 → 西 → 南 → 东** |
| 级牌 | 当前局数 2～A；级牌为本局最大非王牌，2 是普通牌最小点 |
| 发牌 | 每人 27 张，无底牌 |
| 逢人配 | **红心级牌**为万能牌，可补对子、炸弹、顺子、连对、钢板等合法牌型 |
| 牌型 | 单/对/三/三带二/固定 5 张顺子/连对/钢板/4-10 张炸弹/固定 5 张同花顺/四王 |
| 同花顺 | 可压 4 张普通炸弹，或同为 5 张的普通炸弹；6 张及以上普通炸弹可压同花顺 |
| 升级 | 仅头游方升级：头游+二游 +3、头游+三游 +2、头游+末游 +1；炸弹不参与升级；不启用漂牌加级 |
| 进贡 / 还贡 | 非首局发牌后真实换牌：单贡末游给头游，双贡大贡给头游、小贡给二游；真人可选择任一合法贡牌 / 还贡牌 |
| 抗贡 | 单贡方手牌 2 大王可抗贡；双贡方合计 2 大王可抗贡；抗贡后由上一局头游先手 |
| 报牌 | 剩余 ≤ 10 张系统自动报张数 |
| 比赛结束 | 过 A 成功后宣布获胜方并终止比赛 |

> 完整规则见 [docs/rules.md](docs/rules.md)
> AI 信息边界、搜索结构和评测口径见 [docs/ai.md](docs/ai.md)

## 关于"戴长胜" AI

> ⚠️ **致敬声明**：本项目中以"戴长胜"命名的 AI 档位，其牌风倾向（炸弹审慎、控场节奏、配合意识）为向该掼蛋竞技名宿的**致敬性模拟**，并非其本人参与训练或授权。如有侵权疑问请与作者联系。

## 项目结构

```
guandan/
├── src/guandan/      # 源码
│   ├── engine/       # 纯规则逻辑
│   ├── ai/           # AI 策略
│   ├── gui/          # PySide6 桌面界面
│   ├── tui/          # 文本界面（M1）
│   ├── ui/           # 前端共享牌局 session / 展示 helper
│   ├── cli.py        # 命令行入口
│   └── storage/      # 持久化
├── tests/            # pytest + hypothesis 测试
├── docs/             # 规则、ADR、回放协议
└── pyproject.toml
```

## 路线图

- [x] **M0a** 规则引擎 + CLI（v0.1.0）
- [x] M1 TUI 替换 CLI（v0.2.0）
- [x] **M2** AI 1-3 档（v0.3.0）
- [x] **M3** AI 4 档 IS-MCTS（v0.4.0）
- [x] **M4** 戴长胜 AI（v0.5.0）
- [x] **M5** 持久化（v0.6.0）：保存/历史/统计完成
- [x] **M5.1** 断点续局恢复与项目状态校准（v0.6.1）
- [x] **M6.1** 规则口径修复（v0.6.2-v0.6.5）：逆时针行牌、级牌比较、王对子、4-10 张炸弹、同花顺比较
- [x] **M6.2** AI 候选策略与 TUI 视觉收口（v0.6.6）
- [x] **M6.3** 公测版稳定性收口（v0.7.0-beta.1）：AI 连续行牌、防卡死回归、文档与版本号统一
- [x] **M6.4** 公测版回合顺序修复（v0.7.0-beta.2）：当前轮显示隔离、AI 牌权逆时针回归测试
- [x] **M7** AI 对战基准与策略调优（v0.7.0-beta.3）：benchmark、牌墩公共 helper、高阶过牌控制、MCTS 评分升级与残局策略收口
- [x] **M7.1** 规则细节公测补丁（v0.7.0-beta.4）：同花顺/炸弹层级、还贡边界、报牌入口与规则文档再校准
- [x] **M8** 桌面 GUI 首版：PySide6 原生窗口、完整牌局流程、共享 session 层、存档/历史/规则页面
- [x] **M8.1** 事件回放收口：事件流校验重放、GUI/TUI 历史逐步查看、共享回放描述
- [x] **M8.2** GUI 视觉重构：现代牌桌、队伍座位态、缩略牌墩、单排重叠手牌与全页面视觉系统
- [x] **M8.3** 跨局与交互收口：比赛 / 小局统计、交互进贡、异步 AI、存档确认与牌桌式回放
- [x] **M9** AI 能力重构：团队感知 SO-ISMCTS、软证据信念采样、分层候选、结构化 rollout、镜像 Arena 与自对弈调参
- [~] v1.0 发布前调优：更强残局策略、更多 TUI 细节、文档/回放体验完善

## 开发

```bash
# 从级牌 2 连续模拟到成功过 A，并验证每小局事件流
python -m guandan.ai.benchmark --full-match --difficulties 0 --json

# 相同发牌换队复赛，输出胜率、Wilson 区间、Elo、升级差和候选延迟
python -m guandan.ai.arena --candidate 4 --baseline 3 --deals 20 --json

# 固定迭代、跨机器可复现的搜索回归；添加 --full-match 可从 2 打到过 A
python -m guandan.ai.arena --candidate 4 --baseline 3 --deals 8 \
  --deterministic-search --json

# 两阶段自对弈搜索戴长胜风格参数
python -m guandan.ai.tuning --candidates 6 --screening-deals 3 \
  --finalists 2 --final-deals 10 --output tuning-report.json

# 生成 GUI/TUI 视觉验收产物
python scripts/capture_visual_qa.py --output visual-artifacts
```

```bash
# 运行测试（本项目要求 Python 3.10+）
pytest

# 静态检查
ruff check src tests scripts
mypy src

# 全套 CI 检查
ruff check src tests scripts && mypy src && pytest

# AI 对战基准
python -m guandan.ai.benchmark --games 20 --difficulties 0,1,2,3 --json

# 对比两次 AI 基准结果
python -m guandan.ai.benchmark --compare baseline.json current.json --json

# 带回归门禁的 AI 基准对比
python -m guandan.ai.benchmark --compare baseline.json current.json \
  --fail-completion-drop 0.05 --fail-duration-increase 2.0 --fail-turn-increase 20
```

### 当前 M7 基准

- 命令：`python -m guandan.ai.benchmark --games 20 --difficulties 0,1,2,3 --seed-start 800 --max-turns 2000 --json`
- 结果：20/20 完成，完成率 1.0，平均 91.15 回合，平均炸弹数 `[0.3, 0.4]`。
- 胜场：`[2, 18]`；这是混合难度座位基准，1/3 号位难度整体高于 0/2 号位，不作为公平胜率结论。

### M8.1 基准基线

- 固定基线：`benchmarks/v0.8.0b1-mixed-20.json`
- 命令与比较门禁见 [benchmarks/README.md](benchmarks/README.md)
- 当前基线：20/20 完成，平均 92.9 回合，东西/南北胜场 `3/17`，平均炸弹 `[0.25, 0.45]`

### M9 镜像强度基线

- Arena 对每个 seed 连打两局，候选与基线交换东西 / 南北队，避免把发牌和固定队伍优势误判为 AI 强度。
- 戴长胜档使用生产留出 seed 5000-5019 对职业档取得 `21/40`，胜率 52.5%，平均升级差 `+0.40`，候选决策 `p95=0.429s`；Wilson 95% 区间为 37.5%-67.1%，因此作为非回退证据，不宣称统计显著领先。
- 固定迭代回归为 `8/16`，职业 / 戴长胜分别执行 64 / 96 次模拟，候选决策 p95 为 `0.997s`；夜间 CI 要求戴长胜胜率不低于 45%，并上传完整 Arena JSON。
- 参数筛选、复赛和留出摘要见 `benchmarks/ai-v2-style-tuning.json`；小样本 Wilson 95% 区间仍较宽，应持续累计夜间基线，而不是把单次胜率当成绝对棋力。

## 许可

MIT — 见 [LICENSE](LICENSE)

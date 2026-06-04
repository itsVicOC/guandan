# 掼蛋（Guandan）— 本地 TUI 单机版

> 状态：**M2 已完成**（AI 档 0/1/2 + TUI 接 AI 包；档 3/4 在 M3/M4 实现）
> 规则：与全国锦标赛通用口径一致
> AI：5 档（新手 / 进阶 / 高手 / 职业 / **戴长胜**），M2 实现前 3 档

## 特性

- 🎴 严格按全国掼蛋比赛规则：2 副牌 108 张、4 人固定搭档、级牌、进贡/还贡、报牌、漂牌、逢人配、抗贡、过 A
- 🤖 5 档 AI 难度，最高档致敬戴长胜牌风（炸弹吝啬、控场节奏、配合意识、漂牌决策）
- 🔁 每局自动回放 / 历史战绩 / 断点续局
- 💻 终端 TUI（`textual`），零安装依赖，macOS / Linux 主流终端兼容

## 安装

```bash
# 推荐使用 uv
uv venv
uv pip install -e ".[dev]"

# 或用 pip
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 快速开始

```bash
# CLI 模式（M0a 阶段交付）
python -m guandan.cli

# TUI 模式（M1 阶段交付）
guandan
```

## 规则摘要

| 项 | 规则 |
| --- | --- |
| 牌数 | 2 副扑克 108 张 |
| 玩家 | 4 人，**东↔西 / 南↔北** 为同队 |
| 级牌 | 当前局数 2～A，A 为本局最大非王级牌；2 是普通牌最小点 |
| 发牌 | 每人 27 张，无底牌 |
| 逢人配 | **红心级牌** 这 1 张为万能牌 |
| 牌型 | 单/对/三/三带二/顺子/连对/钢板/4-8 张炸弹/同花顺/四王 |
| 升级 | 双上 +3、双下 -3；炸弹数翻倍；过 A 即冠军 |
| 漂牌 | 上游方最后一手出 5 张+级牌炸弹，下局再 +3 |
| 报牌 | 剩余 ≤ 10 张须主动报张数 |

> 完整规则见 [docs/rules.md](docs/rules.md)

## 关于"戴长胜" AI

> ⚠️ **致敬声明**：本项目中以"戴长胜"命名的 AI 档位，其牌风倾向（炸弹吝啬、控场节奏、配合意识、漂牌决策）为向该掼蛋竞技名宿的**致敬性模拟**，并非其本人参与训练或授权。如有侵权疑问请与作者联系。

## 项目结构

```
guandan/
├── src/guandan/      # 源码
│   ├── engine/       # 纯规则逻辑
│   ├── ai/           # AI 策略
│   ├── tui/          # 文本界面（M1）
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
- [ ] M3 AI 4 档（IS-MCTS）
- [ ] M4 戴长胜 AI
- [ ] M5 持久化
- [ ] M6 调优 & v1.0 发布

## 开发

```bash
# 运行测试
pytest

# 静态检查
ruff check src tests
mypy src

# 全套 CI 检查
ruff check src tests && mypy src && pytest
```

## 许可

MIT — 见 [LICENSE](LICENSE)

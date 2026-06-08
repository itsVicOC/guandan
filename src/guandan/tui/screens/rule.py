"""规则说明屏。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

RULES_TEXT = """\
【基础】
• 4 人 2 副牌 108 张
• 固定搭档：东↔西 vs 南↔北
• 每人 27 张，无底牌
• 级牌（2~A）每局不同，本局红心级牌为"逢人配"万能牌

【牌型】
• 单 / 对 / 三 / 三带二
• 顺子（5+ 张连续；A 可作最大 10-J-Q-K-A 或最小 A-2-3-4-5）
• 连对（3+ 对连续对子）
• 钢板 / 三顺（2+ 组连续三张）
• 4-8 张同点 = 炸弹
• 5+ 张同花色顺子 = 同花顺
• 大王×2 + 小王×2 = 四王（最大，全游戏无敌）

【比较】
• 同类型比点数（必要时比张数）
• 炸弹 / 同花顺 / 四王可压任何非炸弹
• 同花顺 > 普通炸弹（同张数）
• 四王 > 一切

【出牌】
• 每人轮流出牌
• 必须与上家同类型且更大，或过牌
• 3 个非 leader 全过 → 本轮结束，最后出牌者（或接风者）开新轮

【接风（借风）】
• 玩家出完最后一手后，若 3 个非 leader 都过牌（无人压）
• 则该玩家对家（队友）自动领出下一轮
• 若最后一手被压，则不接风，由压牌者继续

【四名次】
• 头游：第一个出完手牌（赢家）
• 二游：第二个出完
• 三游：第三个出完
• 末游：最后剩余手牌的人

【升级】
• 头游 + 二游（同队）= +3 级
• 头游 + 三游（同队）= +2 级
• 头游 + 末游（同队）= +1 级
• 炸弹不直接增加升级数
• 输方不降级

【过 A】
• 必须"双上"（头游 + 队友非末游，即头游+二游 或 头游+三游）
• 冲 A 失败则头游方降回 2

【漂牌】
• 上游方在出过 A 之后
• 最后一手出 5 张+级牌炸弹
• 视为"漂"，下局额外 +3

【报牌】
• 手牌 ≤ 10 张时必须报张数
• 报错/漏报违规

【进贡 / 还贡】
• 本局末游向下游进贡最大牌（含王）
• 收贡方还 ≤10 的任意牌
• 进贡方手牌含 大王×2 + 小王×2 可抗贡

【操作键】
• ↑↓←→ 移动光标
• Space 选择 / 取消选牌
• Enter 出牌
• P     过牌
• T     提示（让 AI 推荐一手）
• B     报牌
• ?     查看本规则
• Escape 返回牌桌；从牌桌返回主菜单时会自动保存未完成对局
"""


class RuleScreen(Screen):
    """规则说明屏。"""

    BINDINGS = [
        ("escape", "back", "返回"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Center(), Vertical(id="rule-box"):
            yield Static("📜 掼蛋规则", id="rule-title")
            with VerticalScroll(id="rule-scroll"):
                yield Static(RULES_TEXT)
            yield Button("← 返回", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#rule-title", Static).styles.text_style = "bold"
        self.query_one("#rule-title", Static).styles.color = "yellow"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()

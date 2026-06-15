"""AI 策略抽象。

定义 `AIStrategy` 协议、工厂函数 `make_strategy`、异常 `AINotImplementedError`
以及 `DIFFICULTY_NAMES` 表。

M2 实现档 0/1/2，档 3/4 抛 `AINotImplementedError`。
"""
from __future__ import annotations

from typing import Dict, Protocol

from ..engine.hand import Pattern
from ..engine.state import GameState


class AIStrategy(Protocol):
    """AI 策略协议。

    策略本身只决定 **出什么牌**（或不出 = 返回 None）。是否把"找到牌 → 仍选择过
    牌"的概率过牌逻辑放在调用方共享的 `stochastic.should_pass` 中。
    """

    name: str
    difficulty: int
    uses_stochastic_pass: bool

    def select_pattern(
        self, state: GameState, player: int
    ) -> Pattern | None:
        """为 player 选一个牌型。

        返回 None 表示"无可压之牌 / 不愿出牌"——调用方应据此过牌（且必须是合法过牌
        的时机：不是新一轮领出且 table 非空）。
        """
        ...


class AINotImplementedError(NotImplementedError):
    """请求的 AI 档位尚未实现。"""


# 档位 → 策略类。M2 支持 0/1/2，M3 支持 3，M4 支持 4。
_STRATEGIES: Dict[int, str] = {
    0: "guandan.ai.strategies.novice.NoviceStrategy",
    1: "guandan.ai.strategies.intermediate.IntermediateStrategy",
    2: "guandan.ai.strategies.advanced.AdvancedStrategy",
    3: "guandan.ai.strategies.professional.ProfessionalStrategy",
    4: "guandan.ai.strategies.dachangsheng.DaiChangshengStrategy",
}


# 档位 → 人类可读名（与 `tui/screens/difficulty.py` 的 DIFFICULTIES 保持一致）
DIFFICULTY_NAMES: Dict[int, str] = {
    0: "新手",
    1: "进阶",
    2: "高手",
    3: "职业",
    4: "戴长胜",
}


def make_strategy(difficulty: int) -> AIStrategy:
    """档位 → 策略实例。所有档位已实现。"""
    if difficulty not in _STRATEGIES:
        raise AINotImplementedError(
            f"AI 档 {difficulty} ({DIFFICULTY_NAMES.get(difficulty, '?')}) 不存在"
        )
    path = _STRATEGIES[difficulty]
    mod_name, _, cls_name = path.rpartition(".")
    import importlib

    mod = importlib.import_module(mod_name)
    cls = getattr(mod, cls_name)
    return cls()

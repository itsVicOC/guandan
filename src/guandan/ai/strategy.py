"""AI 策略抽象。

定义 `AIStrategy` 协议、工厂函数 `make_strategy`、异常 `AINotImplementedError`
以及 `DIFFICULTY_NAMES` 表。

五档策略均已实现；编号保持与存档兼容。
"""
from __future__ import annotations

from typing import Dict, Protocol

from ..engine.hand import Pattern
from ..engine.state import GameState


class AIStrategy(Protocol):
    """AI 策略协议。

    策略决定 **出什么牌**（或不出 = 返回 None）。旧策略可选择额外随机过牌；
    当前五档均直接比较过牌与出牌，不再由调用方随机覆写。
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


# 档位 → 策略类。
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

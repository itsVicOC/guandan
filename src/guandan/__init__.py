"""掼蛋 - 本地 TUI 单机版。

包结构：
- engine/  : 纯规则逻辑（牌型、判牌、轮转、升级）
- ai/      : AI 策略（5 档难度）
- tui/     : textual 终端界面（M1 阶段）
- cli.py   : 命令行入口（M0a 阶段）
- storage/ : 持久化（profile / replay / savegame）
"""
from __future__ import annotations

__version__ = "0.7.0b1"
__all__ = ["__version__"]

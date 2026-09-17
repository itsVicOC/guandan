"""掼蛋 - 本地 GUI / TUI 单机版。

包结构：
- engine/  : 纯规则逻辑（牌型、判牌、轮转、升级）
- ai/      : AI 策略（5 档难度）
- gui/     : PySide6 桌面界面
- tui/     : textual 终端界面（M1 阶段）
- ui/      : 前端共享牌局 session / 展示 helper
- cli.py   : 命令行入口（M0a 阶段）
- storage/ : 持久化（profile / replay / savegame）
"""
from __future__ import annotations

import re

__version__ = "0.8.1b2"


def version_label(prefix: str = "v") -> str:
    """Human-readable release label derived from the packaging version.

    PEP 440 spells the beta as ``0.8.1b2``; users see ``v0.8.1-beta.2``.
    Deriving one from the other keeps the GUI title, TUI subtitle and CLI
    banner from drifting apart from pyproject.toml at release time.
    """
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?:(a|b|rc)(\d+))?", __version__)
    if match is None:
        return f"{prefix}{__version__}"
    base, stage, number = match.groups()
    if stage is None:
        return f"{prefix}{base}"
    stage_name = {"a": "alpha", "b": "beta", "rc": "rc"}[stage]
    return f"{prefix}{base}-{stage_name}.{number}"


__all__ = ["__version__", "version_label"]

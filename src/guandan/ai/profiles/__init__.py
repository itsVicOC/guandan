"""AI Profile 加载器。

从 JSON 文件加载 AI 风格配置。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def load_profile(name: str) -> Dict[str, Any]:
    """加载 AI 风格配置文件。

    Args:
        name: 配置文件名（如 "dachangsheng.json" 或 "dachangsheng"）

    Returns:
        配置字典

    Raises:
        FileNotFoundError: 配置文件不存在
        json.JSONDecodeError: JSON 格式错误
    """
    if not name.endswith(".json"):
        name += ".json"

    # 包内路径
    package_dir = Path(__file__).parent
    profile_path = package_dir / name

    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found: {name} (looked in {package_dir})")

    with open(profile_path, encoding="utf-8") as f:
        profile = json.load(f)

    # 简单验证
    _validate_profile(profile)

    return profile


def _validate_profile(profile: Dict[str, Any]) -> None:
    """验证 profile 格式。

    Args:
        profile: 配置字典

    Raises:
        ValueError: 配置格式错误
    """
    required_keys = ["name", "difficulty", "description", "mcts", "style"]
    for key in required_keys:
        if key not in profile:
            raise ValueError(f"Profile missing required key: {key}")

    # 验证 mcts 配置
    mcts = profile["mcts"]
    if "iterations" not in mcts:
        raise ValueError("Profile mcts missing 'iterations'")

    # 验证 style 配置
    style = profile["style"]
    if not isinstance(style, dict):
        raise ValueError("Profile 'style' must be a dict")


__all__ = ["load_profile"]

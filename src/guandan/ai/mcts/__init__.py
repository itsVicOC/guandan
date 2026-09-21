"""Imperfect-information search implementations used by the high-level AIs.

Professional defaults to paired root-action evaluation: every round samples one
hidden-card world and applies all root actions to copies of it.  The budget is
32 evaluations or 240 ms over six representative search actions plus pass and
greedy coverage.  SO-ISMCTS and perfect-information MCTS remain available for
controlled comparisons and focused tests.
"""
from __future__ import annotations

from typing import Dict

from .determinize import determinize
from .information_set import (
    InformationSetNode,
    SearchResult,
    SearchStyle,
    information_set_search,
)
from .node import MCTSNode
from .root_search import root_action_candidates, root_action_search
from .search import mcts_search

__all__ = [
    "MCTS_CONFIG",
    "InformationSetNode",
    "MCTSNode",
    "SearchResult",
    "SearchStyle",
    "determinize",
    "information_set_search",
    "mcts_search",
    "root_action_candidates",
    "root_action_search",
]

# 默认配置
MCTS_CONFIG: Dict[str, int | float | str] = {
    "iterations": 32,
    "time_budget_ms": 240,
    "search_mode": "root",
    "ucb_c": 1.20,
    "prior_weight": 0.18,
    "max_depth": 12,
    "rollout_strategy": 1,
    "top_actions": 6,
    "rollout_max_turns": 40,
    "hand_threshold": 10,
    "widening_c": 1.8,
    "widening_alpha": 0.5,
}

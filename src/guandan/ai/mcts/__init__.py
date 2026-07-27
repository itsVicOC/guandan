"""Monte Carlo tree-search implementations used by the high-level AIs.

The production path is team-aware SO-ISMCTS: every simulation samples a fresh
hidden-card world, while all worlds share a tree keyed by public action history.
The legacy perfect-information MCTS remains exported for compatibility and
focused tests.

Professional defaults cap search at 64 simulations or 240 ms, use 10
representative actions, depth 12, rollout level 2 and a 40-turn rollout limit.
Progressive widening and PUCT-style priors control expansion within that budget.
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
]

# 默认配置
MCTS_CONFIG: Dict[str, int | float] = {
    "iterations": 64,
    "time_budget_ms": 240,
    "ucb_c": 1.20,
    "prior_weight": 0.18,
    "max_depth": 12,
    "rollout_strategy": 2,
    "top_actions": 10,
    "rollout_max_turns": 40,
    "hand_threshold": 10,
    "widening_c": 1.8,
    "widening_alpha": 0.5,
}

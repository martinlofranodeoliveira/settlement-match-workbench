"""Public package interface for settlement_match_workbench.

MIT License
Copyright (c) 2026 Lofrano Tecnologia
"""

from __future__ import annotations

from .solver import solve
from .types import (
    Analysis,
    Edge,
    EdgeAnalysis,
    EdgeClass,
    Limits,
    Objective,
    Pair,
    Problem,
    Result,
    Status,
    VertexAnalysis,
)

__all__ = [
    "Analysis",
    "Edge",
    "EdgeAnalysis",
    "EdgeClass",
    "Limits",
    "Objective",
    "Pair",
    "Problem",
    "Result",
    "Status",
    "VertexAnalysis",
    "solve",
]

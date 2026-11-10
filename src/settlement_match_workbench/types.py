"""Closed immutable DTOs and Enums for settlement_match_workbench.

MIT License
Copyright (c) 2026 Lofrano Tecnologia
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    COMPLETE = "COMPLETE"
    INVALID_INPUT = "INVALID_INPUT"
    UNKNOWN_BUDGET = "UNKNOWN_BUDGET"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class EdgeClass(str, Enum):
    FORCED = "FORCED"
    OPTIONAL = "OPTIONAL"
    GLOBALLY_EXCLUDED = "GLOBALLY_EXCLUDED"


@dataclass(frozen=True, slots=True)
class Edge:
    left_id: str
    right_id: str
    cost: int


@dataclass(frozen=True, slots=True)
class Problem:
    left_ids: tuple[str, ...] | list[str]
    right_ids: tuple[str, ...] | list[str]
    edges: tuple[Edge, ...] | list[Edge]


@dataclass(frozen=True, slots=True)
class Limits:
    max_work: int = 50_000_000


@dataclass(frozen=True, slots=True)
class Pair:
    left_id: str
    right_id: str


@dataclass(frozen=True, slots=True)
class Objective:
    cardinality: int
    cost: int


@dataclass(frozen=True, slots=True)
class EdgeAnalysis:
    left_id: str
    right_id: str
    cost: int
    classification: EdgeClass
    probe_objective: Objective


@dataclass(frozen=True, slots=True)
class VertexAnalysis:
    id: str
    can_be_matched: bool
    can_be_unmatched: bool
    possible_partner_ids: tuple[str, ...]
    forced_partner_id: str | None
    unmatched_probe_objective: Objective | None


@dataclass(frozen=True, slots=True)
class Analysis:
    objective: Objective
    representative: tuple[Pair, ...]
    edges: tuple[EdgeAnalysis, ...]
    left: tuple[VertexAnalysis, ...]
    right: tuple[VertexAnalysis, ...]


@dataclass(frozen=True, slots=True)
class Result:
    status: Status
    code: str
    work_used: int
    analysis: Analysis | None

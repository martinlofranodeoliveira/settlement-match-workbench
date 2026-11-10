"""Bounded all-optimal bipartite matching solver kernel.

MIT License
Copyright (c) 2026 Lofrano Tecnologia
"""

from __future__ import annotations

import re
from typing import Final

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

_MAX_VERTICES_PER_SIDE: Final[int] = 16
_MAX_EDGES: Final[int] = 128
_MAX_EDGE_COST: Final[int] = 1_000_000
_MAX_EDGE_COST_BITS: Final[int] = 20
_MAX_LIMIT_WORK: Final[int] = 100_000_000
_MAX_LIMIT_WORK_BITS: Final[int] = 27
_MAX_TOTAL_COST: Final[int] = _MAX_VERTICES_PER_SIDE * _MAX_EDGE_COST
_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,31}$", re.ASCII)


class _BudgetExhausted(Exception):
    """Raised internally when the logical work meter reaches max_work."""


class _InvariantError(Exception):
    """Raised internally when a flow, path, or optimality invariant fails."""


class _WorkMeter:
    __slots__ = ("max_work", "work")

    def __init__(self, max_work: int) -> None:
        self.max_work: int = max_work
        self.work: int = 0

    def charge(self, units: int = 1) -> None:
        if units < 0:
            raise _InvariantError()
        next_work = self.work + units
        if next_work > self.max_work:
            raise _BudgetExhausted()
        self.work = next_work


class _CanonicalEdge:
    __slots__ = ("left_idx", "right_idx", "cost", "left_id", "right_id")

    def __init__(
        self,
        left_idx: int,
        right_idx: int,
        cost: int,
        left_id: str,
        right_id: str,
    ) -> None:
        self.left_idx: int = left_idx
        self.right_idx: int = right_idx
        self.cost: int = cost
        self.left_id: str = left_id
        self.right_id: str = right_id


def _is_valid_id(value: str) -> bool:
    if len(value) == 0 or len(value) > 32 or not value.isascii():
        return False
    return _ID_RE.fullmatch(value) is not None


def _validate_phase0(problem: Problem, limits: Limits) -> str | None:
    if type(problem) is not Problem or type(limits) is not Limits:
        return "TYPE"

    try:
        max_work = limits.max_work
    except AttributeError:
        return "SHAPE"

    if type(max_work) is not int:
        return "TYPE"
    if max_work < 0 or max_work.bit_length() > _MAX_LIMIT_WORK_BITS or max_work > _MAX_LIMIT_WORK:
        return "LIMITS"

    try:
        left_ids = problem.left_ids
        right_ids = problem.right_ids
        edges = problem.edges
    except AttributeError:
        return "SHAPE"

    if (
        type(left_ids) not in (tuple, list)
        or type(right_ids) not in (tuple, list)
        or type(edges) not in (tuple, list)
    ):
        return "SHAPE"

    if (
        len(left_ids) > _MAX_VERTICES_PER_SIDE
        or len(right_ids) > _MAX_VERTICES_PER_SIDE
        or len(edges) > _MAX_EDGES
    ):
        return "SIZE"

    left_seen: set[str] = set()
    for i in range(len(left_ids)):
        lid = left_ids[i]
        if type(lid) is not str:
            return "TYPE"
        if not _is_valid_id(lid):
            return "ID"
        if lid in left_seen:
            return "DUPLICATE_ID"
        left_seen.add(lid)

    right_seen: set[str] = set()
    for i in range(len(right_ids)):
        rid = right_ids[i]
        if type(rid) is not str:
            return "TYPE"
        if not _is_valid_id(rid):
            return "ID"
        if rid in right_seen:
            return "DUPLICATE_ID"
        right_seen.add(rid)

    edge_seen: set[tuple[str, str]] = set()
    for i in range(len(edges)):
        edge = edges[i]
        if type(edge) is not Edge:
            return "EDGE"
        try:
            el = edge.left_id
            er = edge.right_id
            ec = edge.cost
        except AttributeError:
            return "EDGE"
        if type(el) is not str or type(er) is not str or type(ec) is not int:
            return "TYPE"
        if not _is_valid_id(el) or not _is_valid_id(er):
            return "ID"
        if ec < 0 or ec.bit_length() > _MAX_EDGE_COST_BITS or ec > _MAX_EDGE_COST:
            return "COST"
        if el not in left_seen or er not in right_seen:
            return "UNKNOWN_ID"
        key = (el, er)
        if key in edge_seen:
            return "DUPLICATE_EDGE"
        edge_seen.add(key)

    return None


def _solve_subproblem(
    meter: _WorkMeter,
    n_left: int,
    n_right: int,
    edges: tuple[_CanonicalEdge, ...],
    banned_left: int = -1,
    banned_right: int = -1,
    excluded_edge_idx: int = -1,
) -> tuple[int, int, tuple[int, ...]]:
    # Charge 2 for S and T creation so max_work=0 always exhausts on empty graphs.
    meter.charge(2)

    left_node_of: list[int] = [-1] * n_left
    right_node_of: list[int] = [-1] * n_right
    active_left_nodes: list[int] = []
    active_right_nodes: list[int] = []

    next_node = 1
    for li in range(n_left):
        meter.charge(1)
        if li != banned_left:
            left_node_of[li] = next_node
            active_left_nodes.append(next_node)
            next_node += 1

    for ri in range(n_right):
        meter.charge(1)
        if ri != banned_right:
            right_node_of[ri] = next_node
            active_right_nodes.append(next_node)
            next_node += 1

    source_node = 0
    sink_node = next_node
    num_nodes = sink_node + 1
    if num_nodes > 34:
        raise _InvariantError()

    arc_u: list[int] = []
    arc_v: list[int] = []
    arc_cap: list[int] = []
    arc_cost: list[int] = []

    def _add_residual_pair(u: int, v: int, cost: int) -> int:
        meter.charge(2)
        fwd_idx = len(arc_u)
        arc_u.append(u)
        arc_v.append(v)
        arc_cap.append(1)
        arc_cost.append(cost)
        arc_u.append(v)
        arc_v.append(u)
        arc_cap.append(0)
        arc_cost.append(-cost)
        return fwd_idx

    left_source_arcs: list[int] = []
    for u_node in active_left_nodes:
        left_source_arcs.append(_add_residual_pair(source_node, u_node, 0))

    active_edge_indices: list[int] = []
    active_edge_fwd_arcs: list[int] = []
    for e_idx in range(len(edges)):
        meter.charge(1)
        if e_idx == excluded_edge_idx:
            continue
        ce = edges[e_idx]
        if ce.left_idx == banned_left or ce.right_idx == banned_right:
            continue
        u_node = left_node_of[ce.left_idx]
        v_node = right_node_of[ce.right_idx]
        if u_node <= 0 or v_node <= 0:
            raise _InvariantError()
        fwd_arc = _add_residual_pair(u_node, v_node, ce.cost)
        active_edge_indices.append(e_idx)
        active_edge_fwd_arcs.append(fwd_arc)

    right_sink_arcs: list[int] = []
    for v_node in active_right_nodes:
        right_sink_arcs.append(_add_residual_pair(v_node, sink_node, 0))

    num_arcs = len(arc_u)
    if num_arcs > 320:
        raise _InvariantError()

    max_possible_flow = min(len(active_left_nodes), len(active_right_nodes))
    total_flow = 0
    total_cost = 0

    for _step in range(max_possible_flow + 1):
        meter.charge(num_nodes)
        dist: list[int | None] = [None] * num_nodes
        parent_node: list[int] = [-1] * num_nodes
        parent_arc: list[int] = [-1] * num_nodes
        dist[source_node] = 0

        for _pass in range(num_nodes - 1):
            meter.charge(num_nodes)
            changed = False
            for a_idx in range(num_arcs):
                meter.charge(1)
                if arc_cap[a_idx] > 0:
                    u = arc_u[a_idx]
                    du = dist[u]
                    if du is not None:
                        v = arc_v[a_idx]
                        nd = du + arc_cost[a_idx]
                        dv = dist[v]
                        if dv is None or nd < dv:
                            dist[v] = nd
                            parent_node[v] = u
                            parent_arc[v] = a_idx
                            changed = True
            if not changed:
                break

        # Explicit Bellman-Ford negative-cycle verification pass.
        meter.charge(num_nodes)
        for a_idx in range(num_arcs):
            meter.charge(1)
            if arc_cap[a_idx] > 0:
                u = arc_u[a_idx]
                du = dist[u]
                if du is not None:
                    v = arc_v[a_idx]
                    dv = dist[v]
                    if dv is None or du + arc_cost[a_idx] < dv:
                        raise _InvariantError()

        sink_dist = dist[sink_node]
        if sink_dist is None:
            break

        if total_flow >= max_possible_flow:
            raise _InvariantError()

        path_arcs: list[int] = []
        visited_nodes: set[int] = {sink_node}
        curr = sink_node
        path_cost = 0

        while curr != source_node:
            meter.charge(1)
            a_idx = parent_arc[curr]
            prev = parent_node[curr]
            if a_idx < 0 or prev < 0 or prev in visited_nodes:
                raise _InvariantError()
            if arc_u[a_idx] != prev or arc_v[a_idx] != curr or arc_cap[a_idx] != 1:
                raise _InvariantError()
            visited_nodes.add(prev)
            path_arcs.append(a_idx)
            path_cost += arc_cost[a_idx]
            curr = prev
            if len(path_arcs) >= num_nodes:
                raise _InvariantError()

        if path_cost != sink_dist:
            raise _InvariantError()

        for a_idx in path_arcs:
            meter.charge(1)
            rev_idx = a_idx ^ 1
            if arc_cap[a_idx] != 1 or arc_cap[rev_idx] != 0:
                raise _InvariantError()
            arc_cap[a_idx] = 0
            arc_cap[rev_idx] = 1

        total_flow += 1
        total_cost += path_cost
    else:
        raise _InvariantError()

    # Replay and verify matching and residual capacities.
    matched_edge_indices: list[int] = []
    used_left: set[int] = set()
    used_right: set[int] = set()
    replay_cost = 0

    for i in range(len(active_edge_indices)):
        meter.charge(1)
        e_idx = active_edge_indices[i]
        fwd_arc = active_edge_fwd_arcs[i]
        rev_arc = fwd_arc ^ 1
        cap_fwd = arc_cap[fwd_arc]
        cap_rev = arc_cap[rev_arc]
        if (cap_fwd not in (0, 1)) or (cap_rev != 1 - cap_fwd):
            raise _InvariantError()
        if cap_fwd == 0:
            ce = edges[e_idx]
            if ce.left_idx in used_left or ce.right_idx in used_right:
                raise _InvariantError()
            used_left.add(ce.left_idx)
            used_right.add(ce.right_idx)
            matched_edge_indices.append(e_idx)
            replay_cost += ce.cost

    for i in range(len(active_left_nodes)):
        meter.charge(1)
        fwd_arc = left_source_arcs[i]
        u_node = active_left_nodes[i]
        expected_used = False
        for li in used_left:
            meter.charge(1)
            if left_node_of[li] == u_node:
                expected_used = True
                break
        if expected_used and arc_cap[fwd_arc] != 0:
            raise _InvariantError()
        if not expected_used and arc_cap[fwd_arc] != 1:
            raise _InvariantError()

    for i in range(len(active_right_nodes)):
        meter.charge(1)
        fwd_arc = right_sink_arcs[i]
        v_node = active_right_nodes[i]
        expected_used = False
        for ri in used_right:
            meter.charge(1)
            if right_node_of[ri] == v_node:
                expected_used = True
                break
        if expected_used and arc_cap[fwd_arc] != 0:
            raise _InvariantError()
        if not expected_used and arc_cap[fwd_arc] != 1:
            raise _InvariantError()

    if (
        len(matched_edge_indices) != total_flow
        or replay_cost != total_cost
        or total_flow < 0
        or total_flow > _MAX_VERTICES_PER_SIDE
        or total_cost < 0
        or total_cost > _MAX_TOTAL_COST
    ):
        raise _InvariantError()

    return total_flow, total_cost, tuple(matched_edge_indices)


def solve(problem: Problem, limits: Limits = Limits()) -> Result:
    """Solve the bounded all-optimal 1:1 bipartite matching problem."""
    error_code = _validate_phase0(problem, limits)
    if error_code is not None:
        return Result(
            status=Status.INVALID_INPUT,
            code=error_code,
            work_used=0,
            analysis=None,
        )

    meter = _WorkMeter(limits.max_work)

    try:
        raw_left = problem.left_ids
        raw_right = problem.right_ids
        raw_edges = problem.edges

        left_copy: list[str] = []
        for i in range(len(raw_left)):
            meter.charge(1)
            left_copy.append(raw_left[i])
        if len(left_copy) > 0:
            meter.charge(len(left_copy) * len(left_copy))
            left_copy.sort()
        left_tuple = tuple(left_copy)

        left_index: dict[str, int] = {}
        for idx in range(len(left_tuple)):
            meter.charge(1)
            left_index[left_tuple[idx]] = idx

        right_copy: list[str] = []
        for i in range(len(raw_right)):
            meter.charge(1)
            right_copy.append(raw_right[i])
        if len(right_copy) > 0:
            meter.charge(len(right_copy) * len(right_copy))
            right_copy.sort()
        right_tuple = tuple(right_copy)

        right_index: dict[str, int] = {}
        for idx in range(len(right_tuple)):
            meter.charge(1)
            right_index[right_tuple[idx]] = idx

        edge_triples: list[tuple[str, str, int]] = []
        for i in range(len(raw_edges)):
            meter.charge(1)
            e = raw_edges[i]
            edge_triples.append((e.left_id, e.right_id, e.cost))
        if len(edge_triples) > 0:
            meter.charge(len(edge_triples) * len(edge_triples))
            edge_triples.sort(key=lambda item: (item[0], item[1]))

        canonical_edges_list: list[_CanonicalEdge] = []
        for i in range(len(edge_triples)):
            meter.charge(1)
            lid, rid, cost = edge_triples[i]
            canonical_edges_list.append(
                _CanonicalEdge(
                    left_idx=left_index[lid],
                    right_idx=right_index[rid],
                    cost=cost,
                    left_id=lid,
                    right_id=rid,
                )
            )
        canonical_edges = tuple(canonical_edges_list)

        n_left = len(left_tuple)
        n_right = len(right_tuple)
        n_edges = len(canonical_edges)

        base_k, base_c, rep_edge_indices = _solve_subproblem(
            meter=meter,
            n_left=n_left,
            n_right=n_right,
            edges=canonical_edges,
        )
        base_objective = Objective(cardinality=base_k, cost=base_c)

        rep_edge_set: set[int] = set()
        rep_left_matched: list[bool] = [False] * n_left
        rep_right_matched: list[bool] = [False] * n_right
        rep_pairs_list: list[Pair] = []

        for e_idx in rep_edge_indices:
            meter.charge(1)
            ce = canonical_edges[e_idx]
            rep_edge_set.add(e_idx)
            rep_left_matched[ce.left_idx] = True
            rep_right_matched[ce.right_idx] = True
            rep_pairs_list.append(Pair(left_id=ce.left_id, right_id=ce.right_id))
        representative_pairs = tuple(rep_pairs_list)

        edge_analyses_list: list[EdgeAnalysis] = []
        left_possible_partners: list[list[str]] = [[] for _ in range(n_left)]
        right_possible_partners: list[list[str]] = [[] for _ in range(n_right)]
        left_forced_partner: list[str | None] = [None] * n_left
        right_forced_partner: list[str | None] = [None] * n_right

        for e_idx in range(n_edges):
            meter.charge(1)
            ce = canonical_edges[e_idx]
            if e_idx in rep_edge_set:
                probe_k, probe_c, _ = _solve_subproblem(
                    meter=meter,
                    n_left=n_left,
                    n_right=n_right,
                    edges=canonical_edges,
                    excluded_edge_idx=e_idx,
                )
                meter.charge(1)
                if probe_k > base_k or (probe_k == base_k and probe_c < base_c):
                    raise _InvariantError()
                if probe_k == base_k and probe_c == base_c:
                    edge_class = EdgeClass.OPTIONAL
                else:
                    edge_class = EdgeClass.FORCED
                probe_obj = Objective(cardinality=probe_k, cost=probe_c)
            else:
                rem_k, rem_c, _ = _solve_subproblem(
                    meter=meter,
                    n_left=n_left,
                    n_right=n_right,
                    edges=canonical_edges,
                    banned_left=ce.left_idx,
                    banned_right=ce.right_idx,
                )
                probe_k = rem_k + 1
                probe_c = rem_c + ce.cost
                meter.charge(1)
                if probe_k > base_k or (probe_k == base_k and probe_c < base_c):
                    raise _InvariantError()
                if probe_k == base_k and probe_c == base_c:
                    edge_class = EdgeClass.OPTIONAL
                else:
                    edge_class = EdgeClass.GLOBALLY_EXCLUDED
                probe_obj = Objective(cardinality=probe_k, cost=probe_c)

            if edge_class is not EdgeClass.GLOBALLY_EXCLUDED:
                left_possible_partners[ce.left_idx].append(ce.right_id)
                right_possible_partners[ce.right_idx].append(ce.left_id)
                if edge_class is EdgeClass.FORCED:
                    if (
                        left_forced_partner[ce.left_idx] is not None
                        or right_forced_partner[ce.right_idx] is not None
                    ):
                        raise _InvariantError()
                    left_forced_partner[ce.left_idx] = ce.right_id
                    right_forced_partner[ce.right_idx] = ce.left_id

            edge_analyses_list.append(
                EdgeAnalysis(
                    left_id=ce.left_id,
                    right_id=ce.right_id,
                    cost=ce.cost,
                    classification=edge_class,
                    probe_objective=probe_obj,
                )
            )

        left_analyses_list: list[VertexAnalysis] = []
        for li in range(n_left):
            meter.charge(1)
            lid = left_tuple[li]
            partners = tuple(left_possible_partners[li])
            can_be_matched = len(partners) > 0
            forced_partner = left_forced_partner[li]

            if not rep_left_matched[li]:
                can_be_unmatched = True
                unmatched_probe: Objective | None = None
            else:
                ban_k, ban_c, _ = _solve_subproblem(
                    meter=meter,
                    n_left=n_left,
                    n_right=n_right,
                    edges=canonical_edges,
                    banned_left=li,
                )
                meter.charge(1)
                if ban_k > base_k or (ban_k == base_k and ban_c < base_c):
                    raise _InvariantError()
                can_be_unmatched = ban_k == base_k and ban_c == base_c
                unmatched_probe = Objective(cardinality=ban_k, cost=ban_c)

            if not (can_be_matched or can_be_unmatched):
                raise _InvariantError()
            if forced_partner is not None:
                if can_be_unmatched or not can_be_matched or partners != (forced_partner,):
                    raise _InvariantError()

            left_analyses_list.append(
                VertexAnalysis(
                    id=lid,
                    can_be_matched=can_be_matched,
                    can_be_unmatched=can_be_unmatched,
                    possible_partner_ids=partners,
                    forced_partner_id=forced_partner,
                    unmatched_probe_objective=unmatched_probe,
                )
            )

        right_analyses_list: list[VertexAnalysis] = []
        for ri in range(n_right):
            meter.charge(1)
            rid = right_tuple[ri]
            partners = tuple(right_possible_partners[ri])
            can_be_matched = len(partners) > 0
            forced_partner = right_forced_partner[ri]

            if not rep_right_matched[ri]:
                can_be_unmatched = True
                unmatched_probe = None
            else:
                ban_k, ban_c, _ = _solve_subproblem(
                    meter=meter,
                    n_left=n_left,
                    n_right=n_right,
                    edges=canonical_edges,
                    banned_right=ri,
                )
                meter.charge(1)
                if ban_k > base_k or (ban_k == base_k and ban_c < base_c):
                    raise _InvariantError()
                can_be_unmatched = ban_k == base_k and ban_c == base_c
                unmatched_probe = Objective(cardinality=ban_k, cost=ban_c)

            if not (can_be_matched or can_be_unmatched):
                raise _InvariantError()
            if forced_partner is not None:
                if can_be_unmatched or not can_be_matched or partners != (forced_partner,):
                    raise _InvariantError()

            right_analyses_list.append(
                VertexAnalysis(
                    id=rid,
                    can_be_matched=can_be_matched,
                    can_be_unmatched=can_be_unmatched,
                    possible_partner_ids=partners,
                    forced_partner_id=forced_partner,
                    unmatched_probe_objective=unmatched_probe,
                )
            )

        analysis = Analysis(
            objective=base_objective,
            representative=representative_pairs,
            edges=tuple(edge_analyses_list),
            left=tuple(left_analyses_list),
            right=tuple(right_analyses_list),
        )
        return Result(
            status=Status.COMPLETE,
            code="OK",
            work_used=meter.work,
            analysis=analysis,
        )
    except _BudgetExhausted:
        return Result(
            status=Status.UNKNOWN_BUDGET,
            code="WORK_LIMIT",
            work_used=meter.work,
            analysis=None,
        )
    except _InvariantError:
        return Result(
            status=Status.INTERNAL_ERROR,
            code="INVARIANT",
            work_used=meter.work,
            analysis=None,
        )

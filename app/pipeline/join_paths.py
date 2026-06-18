"""Foreign-key join-path engine.

A student-designed structural component that removes the LLM from the decision of
*how tables connect*. It builds an undirected graph from the database's
foreign-key relationships (nodes are tables, edges are FK links) and computes the
join path between tables with a graph algorithm, rather than hoping the model
infers the correct joins.

This targets the missing_join and wrong_join error classes directly: instead of
trusting the model to know that transactions reach customers through accounts, the
engine derives ``tbl_txn -> tbl_acct -> tbl_cust`` from the FK graph and can hand
the model (or a validation step) the exact ON conditions.

Design notes:
    * The graph is built from injected FK edges, each a
      ``(src_table, src_col, tgt_table, tgt_col)`` tuple - the same shape produced
      by the project's FK inference (FKCandidate) and ground-truth list. The engine
      itself touches no database, so it is fully unit-testable.
    * Multiple FKs between the same pair of tables (e.g. loan.disb_acct_no and
      loan.repay_acct_no both referencing acct.acct_no) are preserved: the join
      step carries the first as canonical and the rest as alternatives.
    * Self-referencing FKs (emp.mgr_emp_no -> emp.emp_no) are not path edges; they
      are exposed separately via ``self_joins`` for self-join queries.
"""
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple

import networkx as nx


@dataclass
class JoinStep:
    """One hop in a join path: ``left_table.left_col = right_table.right_col``.

    ``alternatives`` holds additional ``(left_col, right_col)`` pairs when more
    than one FK connects the same two tables.
    """
    left_table: str
    left_col: str
    right_table: str
    right_col: str
    alternatives: List[Tuple[str, str]] = field(default_factory=list)


class JoinPathEngine:

    def __init__(self, fk_edges: Iterable[Tuple[str, str, str, str]]):
        self._g = nx.Graph()
        self._self_refs: dict = {}  # table -> list of (src_col, tgt_col)
        for src_t, src_c, tgt_t, tgt_c in fk_edges:
            if src_t == tgt_t:
                self._self_refs.setdefault(src_t, []).append((src_c, tgt_c))
                self._g.add_node(src_t)
                continue
            self._g.add_node(src_t)
            self._g.add_node(tgt_t)
            if self._g.has_edge(src_t, tgt_t):
                self._g[src_t][tgt_t]["fks"].append((src_t, src_c, tgt_t, tgt_c))
            else:
                self._g.add_edge(src_t, tgt_t, fks=[(src_t, src_c, tgt_t, tgt_c)])

    @classmethod
    def from_fk_candidates(cls, candidates) -> "JoinPathEngine":
        """Build from objects exposing src_table/src_column/tgt_table/tgt_column
        (e.g. the project's FKCandidate)."""
        return cls(
            (c.src_table, c.src_column, c.tgt_table, c.tgt_column) for c in candidates
        )

    def tables(self) -> set:
        return set(self._g.nodes)

    def path(self, table_a: str, table_b: str) -> Optional[List[JoinStep]]:
        """Shortest join path from ``table_a`` to ``table_b``.

        Returns an empty list when the tables are identical, ``None`` when either
        table is unknown or no path connects them, otherwise the ordered hops.
        """
        if table_a not in self._g or table_b not in self._g:
            return None
        if table_a == table_b:
            return []
        try:
            node_path = nx.shortest_path(self._g, table_a, table_b)
        except nx.NetworkXNoPath:
            return None
        return self._steps_along(node_path)

    def connect(self, tables: Iterable[str]) -> Optional[List[JoinStep]]:
        """Join tree connecting every requested table.

        Greedily grows a connected set: each not-yet-included table is reached via
        the shortest path from the nearest already-included table, so every hop
        joins a new table onto one already present (a valid JOIN order). Returns
        ``None`` if any requested table is unknown or unreachable, an empty list
        for zero or one table.
        """
        requested = list(dict.fromkeys(tables))  # de-dupe, keep order
        if any(t not in self._g for t in requested):
            return None
        if len(requested) <= 1:
            return []

        included = {requested[0]}
        steps: List[JoinStep] = []
        for target in requested[1:]:
            if target in included:
                continue
            node_path = self._nearest_path(included, target)
            if node_path is None:
                return None
            steps.extend(self._steps_along(node_path))
            included.update(node_path)
        return steps

    def self_joins(self, table: str) -> List[JoinStep]:
        """Self-referencing FKs on a table (for self-join queries)."""
        return [
            JoinStep(table, src_c, table, tgt_c)
            for src_c, tgt_c in self._self_refs.get(table, [])
        ]

    def to_sql(self, base_table: str, steps: List[JoinStep]) -> str:
        """Render ``base_table`` plus a sequence of JOIN clauses."""
        parts = [base_table]
        for s in steps:
            parts.append(
                f"JOIN {s.right_table} ON {s.left_table}.{s.left_col} "
                f"= {s.right_table}.{s.right_col}"
            )
        return " ".join(parts)

    # -- internals --------------------------------------------------------- #
    def _nearest_path(self, sources, target) -> Optional[List[str]]:
        """Shortest path from the nearest source node to target (None if none).

        Sources are tried in sorted order so ties resolve deterministically.
        """
        best = None
        for src in sorted(sources):
            try:
                p = nx.shortest_path(self._g, src, target)
            except nx.NetworkXNoPath:
                continue
            if best is None or len(p) < len(best):
                best = p
        return best

    def _steps_along(self, node_path: List[str]) -> List[JoinStep]:
        steps = []
        for frm, to in zip(node_path, node_path[1:]):
            steps.append(self._step(frm, to))
        return steps

    def _step(self, frm: str, to: str) -> JoinStep:
        options: List[Tuple[str, str]] = []
        for (st, sc, tt, tc) in self._g[frm][to]["fks"]:
            if st == frm and tt == to:
                options.append((sc, tc))
            elif st == to and tt == frm:
                options.append((tc, sc))
        canonical = options[0]
        return JoinStep(
            left_table=frm,
            left_col=canonical[0],
            right_table=to,
            right_col=canonical[1],
            alternatives=options[1:],
        )

"""Join validation for generated SQL, backed by the FK join-path engine.

This is the runtime half of the join-path technique. It parses a generated query
with sqlglot, resolves table aliases, and checks whether the tables the query
references are actually connected by join conditions. When they are not (a missing
join / accidental cross product), it asks the JoinPathEngine for the correct FK
join path and returns it as a hint, which the engine then feeds back through the
self-correction loop so the model can rewrite the query with the right joins.

The validator is deliberately conservative: it only flags a query when it is
confident (two or more base tables that the query leaves disconnected), and it
bails out - reporting OK - on anything it cannot analyse cleanly (parse errors,
sub-queries or derived tables in the FROM clause, unqualified join columns). A
validator that wrongly flagged correct queries would trigger harmful re-prompts,
so silence beats a false positive.

Scope of this version: missing-join detection. Wrong-join detection (a join on
columns that do not correspond to any FK) is intentionally left out for now, since
non-FK joins can be legitimate and flagging them risks false positives.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import networkx as nx
import sqlglot
from sqlglot import exp

from .join_paths import JoinPathEngine


@dataclass
class ValidationResult:
    ok: bool
    reason: Optional[str] = None
    tables: List[str] = field(default_factory=list)
    hint: Optional[str] = None


class JoinValidator:

    def __init__(self, engine: JoinPathEngine, dialect: str = "tsql"):
        self._engine = engine
        self._dialect = dialect

    def validate(self, sql: Optional[str]) -> ValidationResult:
        info = self._analyze(sql)
        if info is None:
            return ValidationResult(ok=True)
        tables, links = info
        if len(tables) < 2:
            return ValidationResult(ok=True, tables=sorted(tables))

        g = nx.Graph()
        g.add_nodes_from(tables)
        for (a, _, b, _) in links:
            if a in tables and b in tables:
                g.add_edge(a, b)

        if nx.is_connected(g):
            return ValidationResult(ok=True, tables=sorted(tables))

        return ValidationResult(
            ok=False,
            reason="missing_join",
            tables=sorted(tables),
            hint=self._hint(sorted(tables)),
        )

    def _hint(self, tables: List[str]) -> Optional[str]:
        steps = self._engine.connect(tables)
        if not steps:
            return None
        base = tables[0]
        return (
            "The referenced tables are not all joined. The foreign-key join path "
            f"is: {self._engine.to_sql(base, steps)}"
        )

    # -- parsing ----------------------------------------------------------- #
    def _analyze(self, sql: Optional[str]):
        """Return (base_tables, join_links) for the top-level query, or None when
        the query cannot be analysed cleanly (so the caller treats it as OK)."""
        if not sql or not sql.strip():
            return None
        try:
            tree = sqlglot.parse_one(sql, read=self._dialect)
        except Exception:
            return None
        if tree is None:
            return None

        select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
        if select is None:
            return None

        from_ = select.args.get("from_") or select.args.get("from")
        joins = select.args.get("joins") or []
        table_exprs = []
        if from_ is not None:
            table_exprs.append(from_.this)
        for j in joins:
            table_exprs.append(j.this)

        tables = set()
        alias_map = {}
        for te in table_exprs:
            if not isinstance(te, exp.Table):
                return None  # sub-query / derived table -> bail conservatively
            real = te.name
            tables.add(real)
            alias_map[te.alias_or_name] = real
            alias_map[real] = real

        links: List[Tuple[str, str, str, str]] = []
        for j in joins:
            on = j.args.get("on")
            if on is not None:
                links.extend(self._equalities(on, alias_map))
        where = select.args.get("where")
        if where is not None:
            links.extend(self._equalities(where, alias_map))

        return tables, links

    @staticmethod
    def _equalities(node, alias_map) -> List[Tuple[str, str, str, str]]:
        """Column = column equalities between two distinct known tables."""
        out = []
        for eq in node.find_all(exp.EQ):
            left, right = eq.left, eq.right
            if isinstance(left, exp.Column) and isinstance(right, exp.Column):
                lt = alias_map.get(left.table)
                rt = alias_map.get(right.table)
                if lt and rt and lt != rt:
                    out.append((lt, left.name, rt, right.name))
        return out

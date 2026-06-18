"""Value validation for generated SQL, backed by the value-domain index.

The runtime half of the value-domain technique. It parses a generated query with
sqlglot, resolves table aliases (the same skeleton the join validator uses), and
checks every ``column = 'literal'`` / ``column IN (...)`` predicate against the set
of values that actually occur in that column. When the model filters on a code that
does not exist - ``stat_cd = 'ACTIVE'`` on an account whose statuses are
``'OPEN'/'CLOSED'`` - the predicate is flagged and a hint is produced naming the
valid domain and, where the label map allows, the corrected code. The engine then
feeds that hint back through a single re-prompt so the model rewrites the filter.

Conservatism mirrors the join validator: a column is checked only when its table can
be resolved with confidence and the column is in the index; everything else is
skipped, and a parse failure reports OK. The index itself never flags an unindexed
column, so the worst case is silence, never a false positive that would trigger a
harmful re-prompt. Predicates are scanned across the whole tree (so a coded literal
inside a CASE or a join's ON clause is covered too), but only literal comparisons are
considered - ``column = column`` join equalities are ignored.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import sqlglot
from sqlglot import exp

from .value_index import ValueDomainIndex


@dataclass
class ValueViolation:
    table: str
    column: str
    value: str
    suggestion: Optional[str] = None
    domain_desc: str = ""


@dataclass
class ValueValidationResult:
    ok: bool
    violations: List[ValueViolation] = field(default_factory=list)
    hint: Optional[str] = None


class ValueValidator:

    def __init__(self, index: ValueDomainIndex, dialect: str = "tsql"):
        self._index = index
        self._dialect = dialect

    def validate(self, sql: Optional[str]) -> ValueValidationResult:
        parsed = self._parse(sql)
        if parsed is None:
            return ValueValidationResult(ok=True)
        tree, tables, alias_map = parsed

        seen = set()
        violations: List[ValueViolation] = []
        for col, value in self._literal_predicates(tree):
            table = self._resolve_table(col, tables, alias_map)
            if table is None:
                continue
            column = col.name
            if not self._index.has_column(table, column):
                continue
            if self._index.is_valid(table, column, value):
                continue
            key = (table, column.casefold(), str(value).casefold())
            if key in seen:
                continue
            seen.add(key)
            violations.append(ValueViolation(
                table=table,
                column=column,
                value=str(value),
                suggestion=self._index.suggest(table, column, value),
                domain_desc=self._index.describe(table, column) or "",
            ))

        if not violations:
            return ValueValidationResult(ok=True)
        return ValueValidationResult(ok=False, violations=violations, hint=self._hint(violations))

    def diagnose(self, sql: Optional[str]) -> str:
        """Category for a query, for a no-side-effect sweep over a benchmark log:
        'not_analyzable', 'no_literal_predicate', 'all_valid', or
        'out_of_domain_flagged'."""
        parsed = self._parse(sql)
        if parsed is None:
            return "not_analyzable"
        tree, tables, alias_map = parsed
        checked = 0
        for col, value in self._literal_predicates(tree):
            table = self._resolve_table(col, tables, alias_map)
            if table is None or not self._index.has_column(table, col.name):
                continue
            checked += 1
            if not self._index.is_valid(table, col.name, value):
                return "out_of_domain_flagged"
        return "all_valid" if checked else "no_literal_predicate"

    # -- hint -------------------------------------------------------------- #
    @staticmethod
    def _hint(violations: List[ValueViolation]) -> str:
        lines = []
        for v in violations:
            where = f" (table {v.table})" if v.table else ""
            line = (f"- `{v.column} = '{v.value}'`{where} is not a valid value; "
                    f"valid values are: {v.domain_desc}.")
            if v.suggestion:
                line += f" Use '{v.suggestion}'."
            lines.append(line)
        return ("Some filter values in the query do not exist in the database:\n"
                + "\n".join(lines)
                + "\nRewrite the query using the valid values shown, keeping everything else the same.")

    # -- parsing ----------------------------------------------------------- #
    def _parse(self, sql: Optional[str]):
        """Return (tree, base_tables, alias_map) or None when unanalysable."""
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
                continue  # derived table / sub-query in FROM: skip it, don't bail
            real = te.name
            tables.add(real)
            alias_map[te.alias_or_name] = real
            alias_map[real] = real

        if not tables:
            return None
        return tree, tables, alias_map

    def _literal_predicates(self, tree) -> List[Tuple[exp.Column, str]]:
        """Every (column, literal_value) from ``col = lit`` and ``col IN (lits)``
        anywhere in the tree. ``col = col`` equalities are excluded."""
        out: List[Tuple[exp.Column, str]] = []
        for eq in tree.find_all(exp.EQ):
            pair = self._col_lit(eq.left, eq.right)
            if pair is not None:
                out.append(pair)
        for node in tree.find_all(exp.In):
            col = node.this
            if isinstance(col, exp.Column):
                for e in (node.expressions or []):
                    val = self._lit_value(e)
                    if val is not None:
                        out.append((col, val))
        return out

    @classmethod
    def _col_lit(cls, left, right):
        if isinstance(left, exp.Column) and isinstance(right, exp.Literal):
            val = cls._lit_value(right)
            return (left, val) if val is not None else None
        if isinstance(right, exp.Column) and isinstance(left, exp.Literal):
            val = cls._lit_value(left)
            return (right, val) if val is not None else None
        return None

    @staticmethod
    def _lit_value(node) -> Optional[str]:
        if isinstance(node, exp.Literal) and node.this is not None:
            return str(node.this)
        return None

    def _resolve_table(self, col: exp.Column, tables, alias_map) -> Optional[str]:
        """Which base table does this column belong to? Returns None when it cannot
        be determined confidently (so the predicate is skipped)."""
        if col.table:
            return alias_map.get(col.table)  # qualified: resolve alias, else None
        if len(tables) == 1:
            return next(iter(tables))
        # Unqualified with several tables: resolve only if exactly one of them has
        # this column in the index; otherwise it is ambiguous -> skip.
        owners = [t for t in tables if self._index.has_column(t, col.name)]
        return owners[0] if len(owners) == 1 else None

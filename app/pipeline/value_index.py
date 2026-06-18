"""Value-domain index for catching out-of-domain literals in generated SQL.

The model frequently emits status / type code literals that do not exist in the
database: ``'ACTIVE'`` where the column stores ``'OPEN'``, ``'individual'`` where
it stores ``'PF'``, ``1`` where it stores ``'OPEN'``. These are knowledge errors -
the coding scheme is opaque and not guessable, and the same word maps to different
codes in different tables (account status ``'OPEN'`` vs loan/card status
``'ACTIVE'``). This index holds, per low-cardinality column, the set of values that
actually occur, plus an optional human-label map for the opaque coded columns, so a
validator can flag an impossible literal and a repair step can hand the model the
real domain (and, where possible, the corrected code).

Design notes:
  * The index is a pure data structure built from a plain dict, so it is fully
    testable without a database.
  * ``make_source_fetch`` / ``build_value_index`` do the live work (pick the
    low-cardinality coded columns, pull their distinct values from the source DB).
  * Domains are keyed by (table, column) with identifiers casefolded and stripped
    of schema prefixes and quoting, because ``stat_cd`` exists in several tables
    with different domains - the table qualifier is essential.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

# ---------------------------------------------------------------------------
# Hand-authored labels for the opaque coded columns the diagnostic exposed.
# Same epistemic status as SYNTHETIC_DB_GROUND_TRUTH in fk_inference: this is the
# database's data dictionary, which any real deployment would be given. Codes here
# are the stored values; each maps to the natural-language phrases a question might
# use. Only columns whose codes are NOT guessable from the value set are listed;
# columns where the natural word equals the stored code (e.g. loan stat_cd =
# 'ACTIVE') need no entry, since the auto-derived domain already contains it.
# ---------------------------------------------------------------------------
SYNTHETIC_DB_VALUE_LABELS: dict[tuple[str, str], dict[str, list[str]]] = {
    ("tbl_cust", "cust_tp"): {
        "PF": ["individual", "individuals", "personal", "person",
               "natural person", "retail", "private"],
        "PJ": ["corporate", "corporates", "company", "companies", "business",
               "businesses", "legal entity", "commercial", "organization"],
    },
    # Account and branch status: questions say "active"/"open", column stores 'OPEN'
    # (gold uses 'OPEN'; the model wrongly guesses 'ACTIVE'). Closed-side labels are
    # left out rather than guessed; the auto-derived domain supplies the full set.
    ("tbl_acct", "stat_cd"): {
        "OPEN": ["active", "open", "current", "live"],
    },
    ("tbl_br", "stat_cd"): {
        "OPEN": ["active", "open", "operating", "operational"],
    },
}

# Column-name patterns that mark a coded / categorical column worth indexing.
DEFAULT_CODE_COLUMN_SUFFIXES = (
    "_cd", "_code", "_ind", "_tp", "_type", "_flag", "_status", "_stat",
)
DEFAULT_CODE_COLUMN_NAMES = ("status", "type", "category", "categ", "state")


def _norm(value) -> str:
    """Casefold + strip for case-insensitive value/label comparison."""
    return str(value).strip().casefold()


def _norm_ident(name: str) -> str:
    """Normalize a table/column identifier: drop schema, quoting, casefold."""
    if name is None:
        return ""
    text = str(name).strip()
    text = text.split(".")[-1]                 # schema.table -> table
    text = re.sub(r'^[\[`"]+|[\]`"]+$', "", text.strip())
    return text.casefold()


def looks_like_code_column(column: str) -> bool:
    """Heuristic: does this column name look like a categorical/code column?"""
    c = _norm_ident(column)
    if c in DEFAULT_CODE_COLUMN_NAMES:
        return True
    return any(c.endswith(suf) for suf in DEFAULT_CODE_COLUMN_SUFFIXES)


@dataclass
class ColumnDomain:
    """The set of values that actually occur in one column, plus optional labels."""

    table: str
    column: str
    values: set                       # original-case stored values, as strings
    labels: dict = field(default_factory=dict)   # code -> [human labels]
    _value_lookup: dict = field(default_factory=dict, repr=False)
    _label_lookup: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self.values = {str(v).strip() for v in self.values if v is not None and str(v).strip() != ""}
        self._value_lookup = {_norm(v): v for v in self.values}
        self._label_lookup = {}
        for code, labels in (self.labels or {}).items():
            for lab in labels:
                self._label_lookup[_norm(lab)] = code

    def is_valid(self, value) -> bool:
        return _norm(value) in self._value_lookup

    def suggest(self, value) -> Optional[str]:
        """Best guess at the correct stored value for an out-of-domain literal.

        Tries, in order: (1) an exact human-label match (``individual`` -> ``PF``),
        (2) a close string match against the stored values (``Savings`` ->
        ``SAVINGS``). Returns ``None`` if nothing is confident enough.
        """
        nv = _norm(value)
        if nv in self._label_lookup:
            return self._label_lookup[nv]
        # Substring label match (e.g. "corporate customers" contains "corporate").
        for lab, code in self._label_lookup.items():
            if lab in nv or nv in lab:
                return code
        close = difflib.get_close_matches(nv, list(self._value_lookup.keys()), n=1, cutoff=0.82)
        if close:
            return self._value_lookup[close[0]]
        return None

    def describe(self, max_values: int = 12) -> str:
        """Human string of the domain (+ labels) for a repair prompt."""
        vals = sorted(self.values, key=str.casefold)
        shown = vals[:max_values]
        out = ", ".join(repr(v) for v in shown)
        if len(vals) > max_values:
            out += f", ... ({len(vals)} total)"
        if self.labels:
            pairs = [f"{code}={'/'.join(labs[:3])}" for code, labs in self.labels.items()]
            out += "  [meaning: " + "; ".join(pairs) + "]"
        return out


class ValueDomainIndex:
    """Lookup of per-column value domains, keyed by normalized (table, column)."""

    def __init__(self, domains: Optional[dict] = None):
        # domains: {(table, col): ColumnDomain}  (keys will be normalized)
        self._domains: dict[tuple[str, str], ColumnDomain] = {}
        for key, dom in (domains or {}).items():
            self._domains[(_norm_ident(key[0]), _norm_ident(key[1]))] = dom

    def __len__(self) -> int:
        return len(self._domains)

    def columns(self) -> list[tuple[str, str]]:
        return list(self._domains.keys())

    def get(self, table: str, column: str) -> Optional[ColumnDomain]:
        return self._domains.get((_norm_ident(table), _norm_ident(column)))

    def has_column(self, table: str, column: str) -> bool:
        return (_norm_ident(table), _norm_ident(column)) in self._domains

    def is_valid(self, table: str, column: str, value) -> bool:
        """True if the value is in-domain OR the column is not indexed (skip)."""
        dom = self.get(table, column)
        return True if dom is None else dom.is_valid(value)

    def suggest(self, table: str, column: str, value) -> Optional[str]:
        dom = self.get(table, column)
        return dom.suggest(value) if dom is not None else None

    def describe(self, table: str, column: str, max_values: int = 12) -> Optional[str]:
        dom = self.get(table, column)
        return dom.describe(max_values) if dom is not None else None


# ---------------------------------------------------------------------------
# Builders (the live, DB-touching part). Kept thin and injected so the index and
# its consumers stay unit-testable without a database.
# ---------------------------------------------------------------------------
def make_source_fetch(source_engine, schema: str = "bank") -> Callable[[str, str], list]:
    """Return a ``fetch_distinct(table, column) -> list[value]`` over the source DB.

    Uses MS SQL Server bracket quoting. Returns [] on any per-column error so one
    bad column never aborts the whole build.
    """
    from sqlalchemy import text

    def fetch(table: str, column: str) -> list:
        sql = f"SELECT DISTINCT [{column}] FROM [{schema}].[{table}] WHERE [{column}] IS NOT NULL"
        try:
            with source_engine.connect() as conn:
                return [r[0] for r in conn.execute(text(sql)).fetchall()]
        except Exception:
            return []

    return fetch


def build_value_index(
    columns: Iterable[tuple],
    fetch_distinct: Callable[[str, str], list],
    label_map: Optional[dict] = None,
    max_cardinality: int = 25,
    include: Iterable[tuple[str, str]] = (),
    exclude: Iterable[tuple[str, str]] = (),
) -> ValueDomainIndex:
    """Build a ValueDomainIndex.

    ``columns``: iterable of (table, column, distinct_count). A column is indexed
    when it is low-cardinality (``distinct_count <= max_cardinality``) and looks
    like a coded column, OR it is force-listed in ``include``; minus ``exclude``.
    ``fetch_distinct``: supplies the actual distinct values per chosen column.
    ``label_map``: {(table, col): {code: [labels]}} merged onto matching domains.
    """
    label_map = label_map or {}
    include_set = {(_norm_ident(t), _norm_ident(c)) for t, c in include}
    exclude_set = {(_norm_ident(t), _norm_ident(c)) for t, c in exclude}
    norm_labels = {(_norm_ident(t), _norm_ident(c)): v for (t, c), v in label_map.items()}

    domains: dict[tuple[str, str], ColumnDomain] = {}
    for row in columns:
        table, column = row[0], row[1]
        distinct_count = row[2] if len(row) > 2 else None
        key = (_norm_ident(table), _norm_ident(column))
        if key in exclude_set:
            continue
        forced = key in include_set
        low_card = distinct_count is not None and distinct_count <= max_cardinality
        if not forced and not (low_card and looks_like_code_column(column)):
            continue
        values = {str(v).strip() for v in fetch_distinct(table, column)
                  if v is not None and str(v).strip() != ""}
        if not values:
            continue
        domains[key] = ColumnDomain(
            table=_norm_ident(table),
            column=_norm_ident(column),
            values=values,
            labels=norm_labels.get(key, {}),
        )
    return ValueDomainIndex(domains)

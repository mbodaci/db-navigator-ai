"""Code glossary for proactive context injection.

The value-domain validator (the reactive technique) can only catch the ~16% of
value_mapping errors where the model invents a non-existent code. The larger slices
- the model picking a wrong-but-valid code, or simply not knowing what an opaque
code means - are knowledge gaps that no post-hoc check can close. This module builds
the other half of the answer: a compact code dictionary handed to the model *before*
it generates, so it uses the right code from the start.

Two sources, mirroring the data dictionary a real deployment would have:
  * Lookup-backed columns (account type, transaction type, loan product) get their
    descriptions straight from the lookup tables in the database - authoritative,
    no guessing.
  * Bare coded columns (status, customer type, debit/credit, NPL flag, ...) get
    hand descriptions, same epistemic status as the FK ground truth.

The critical content is the per-table ``stat_cd`` split: the synthetic DB codes the
same concept differently per table ("active" is ``OPEN`` for accounts, ``ACTIVE``
for loans/cards/customers, ``1`` for branches/employees), which is a leading cause
of value_mapping errors. The glossary makes that explicit.

The class is a pure data structure; the lookup fetch is injected so it is testable
without a database.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from typing import Callable, Dict, Optional, Tuple

Key = Tuple[str, str]

# --------------------------------------------------------------------------- #
# Hand-authored descriptions for the bare coded columns (the data dictionary).
# Domains are taken from the live column-value diagnostic. The same concept is
# coded differently per table, so each table's status column is listed separately.
# --------------------------------------------------------------------------- #
CODE_DESCRIPTIONS: Dict[Key, Dict[str, str]] = {
    ("tbl_cust", "cust_tp"): {
        "PF": "individual / personal customer (natural person)",
        "PJ": "corporate / business customer (legal entity)",
    },
    ("tbl_guar", "guar_tp"): {
        "PF": "individual guarantor (natural person)",
        "PJ": "corporate guarantor (legal entity)",
    },
    ("tbl_cust", "stat_cd"): {
        "ACTIVE": "active customer",
        "BLOCKED": "blocked customer",
        "DORMANT": "dormant customer",
    },
    ("tbl_acct", "stat_cd"): {
        "OPEN": "active / open account",
        "DORMANT": "dormant account",
        "FROZEN": "frozen account",
    },
    ("tbl_card", "stat_cd"): {
        "ACTIVE": "active card",
        "BLOCKED": "blocked card",
        "EXPIRED": "expired card",
    },
    ("tbl_loan", "stat_cd"): {
        "ACTIVE": "active / outstanding loan",
        "CLOSED": "closed / repaid loan",
    },
    ("tbl_br", "stat_cd"): {
        "1": "active / operating branch",
        "0": "inactive / closed branch",
    },
    ("tbl_emp", "stat_cd"): {
        "1": "active / current employee",
        "0": "inactive / former employee",
    },
    ("tbl_coll", "stat_cd"): {"ACTIVE": "active collateral"},
    ("tbl_guar", "stat_cd"): {"ACTIVE": "active guarantee"},
    ("tbl_txn", "stat_cd"): {"POST": "posted transaction"},
    ("tbl_txn", "dr_cr_ind"): {"D": "debit", "C": "credit"},
    ("tbl_txn_tp", "dr_cr_ind"): {"D": "debit", "C": "credit"},
    ("tbl_loan", "npl_flag"): {
        "Y": "non-performing loan (NPL, in default)",
        "N": "performing loan",
    },
    ("tbl_cust", "gender_cd"): {"M": "male", "F": "female"},
    ("tbl_card", "card_tp"): {"CREDIT": "credit card", "DEBIT": "debit card"},
    ("tbl_coll", "coll_tp"): {
        "REAL_ESTATE": "real estate", "VEHICLE": "vehicle", "EQUIPMENT": "equipment",
    },
}

# Coded columns whose descriptions live in a lookup table: (lookup_table, code_col,
# preferred_name_col). The fetch falls back to auto-detecting the name column.
LOOKUP_SOURCES: Dict[Key, Tuple[str, str, str]] = {
    ("tbl_acct", "acct_tp_cd"): ("tbl_acct_tp", "acct_tp_cd", "acct_tp_nm"),
    ("tbl_txn", "txn_tp_cd"): ("tbl_txn_tp", "txn_tp_cd", "txn_tp_nm"),
    ("tbl_loan", "prod_cd"): ("tbl_loan_prod", "prod_cd", "prod_nm"),
}

_NAME_COL_PATTERNS = ("_nm", "_name", "_desc", "_descr", "_label", "_categ", "_title")


def _pick_name_col(columns, code_col: str) -> Optional[str]:
    """Choose the human-readable name column of a lookup table."""
    lowered = [(c, c.casefold()) for c in columns]
    code = code_col.casefold()
    for c, cl in lowered:
        if cl != code and any(cl.endswith(suf) for suf in _NAME_COL_PATTERNS):
            return c
    # fall back to the first column that is neither the code nor an id/date/amount
    for c, cl in lowered:
        if cl == code:
            continue
        if any(tok in cl for tok in ("_id", "_no", "_dt", "_date", "_amt", "_cd", "_ts")):
            continue
        return c
    return None


class CodeGlossary:
    """An ordered map (table, column) -> {code: description}, renderable as text."""

    def __init__(self, entries: Optional["OrderedDict[Key, Dict[str, str]]"] = None):
        self._entries: "OrderedDict[Key, Dict[str, str]]" = OrderedDict(entries or {})

    def __len__(self) -> int:
        return len(self._entries)

    def columns(self):
        return list(self._entries.keys())

    def get(self, table: str, column: str) -> Optional[Dict[str, str]]:
        return self._entries.get((table, column))

    def add(self, table: str, column: str, codes: Dict[str, str]) -> None:
        key = (table, column)
        merged = dict(self._entries.get(key, {}))
        merged.update({str(k): str(v) for k, v in codes.items()})
        self._entries[key] = merged

    def render(self, header: Optional[str] = None) -> str:
        """Format the glossary as a compact, prompt-ready block, grouped by table."""
        if not self._entries:
            return ""
        head = header or (
            "Code dictionary for this database. Use these exact codes in WHERE "
            "clauses; the same concept can have a different code in each table:"
        )
        # Group columns under each table, tables in first-seen order.
        by_table: "OrderedDict[str, list]" = OrderedDict()
        for (table, column), codes in self._entries.items():
            by_table.setdefault(table, []).append((column, codes))

        lines = [head]
        for table, cols in by_table.items():
            lines.append(f"  {table}:")
            for column, codes in cols:
                pairs = "; ".join(f"{code} = {desc}" for code, desc in codes.items())
                lines.append(f"    {column}: {pairs}")
        return "\n".join(lines)


def make_lookup_fetch(source_engine, schema: str = "bank") -> Callable[..., Dict[str, str]]:
    """Return ``fetch(lookup_table, code_col, name_col_guess) -> {code: name}`` over
    the source DB, auto-detecting the name column when the guess is absent."""
    from sqlalchemy import text

    def fetch(lookup_table: str, code_col: str, name_col_guess: Optional[str] = None) -> Dict[str, str]:
        try:
            with source_engine.connect() as conn:
                cols = [r[0] for r in conn.execute(text(
                    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = :s AND TABLE_NAME = :t"
                ), {"s": schema, "t": lookup_table}).fetchall()]
                name_col = name_col_guess if name_col_guess in cols else _pick_name_col(cols, code_col)
                if not name_col:
                    return {}
                rows = conn.execute(text(
                    f"SELECT [{code_col}], [{name_col}] FROM [{schema}].[{lookup_table}]"
                )).fetchall()
                return {str(c).strip(): str(n).strip()
                        for c, n in rows if c is not None and str(n).strip()}
        except Exception:
            return {}

    return fetch


def build_code_glossary(
    fetch_lookup: Callable[..., Dict[str, str]],
    hand: Optional[Dict[Key, Dict[str, str]]] = None,
    lookups: Optional[Dict[Key, Tuple[str, str, str]]] = None,
    only_columns: Optional[set] = None,
) -> CodeGlossary:
    """Assemble the glossary from the lookup tables and the hand-authored map.

    ``only_columns``: if given, restrict to these (table, column) keys (e.g. the
    columns actually present in ``enriched_columns``), so the glossary never
    references a column the database does not have.
    """
    hand = CODE_DESCRIPTIONS if hand is None else hand
    lookups = LOOKUP_SOURCES if lookups is None else lookups

    def allowed(key: Key) -> bool:
        return only_columns is None or key in only_columns

    glossary = CodeGlossary()
    # Lookup-backed first (authoritative names), then hand descriptions on top.
    for key, (ltable, lcode, lname) in lookups.items():
        if not allowed(key):
            continue
        names = fetch_lookup(ltable, lcode, lname)
        if names:
            glossary.add(key[0], key[1], names)
    for key, codes in hand.items():
        if allowed(key):
            glossary.add(key[0], key[1], codes)
    return glossary

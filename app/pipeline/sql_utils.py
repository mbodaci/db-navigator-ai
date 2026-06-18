"""Shared SQL helpers for the accuracy pipeline.

These mirror the post-processing and execution behaviour already used by the
Streamlit app and the benchmark so the pipeline produces identical results on
the baseline path. They are centralised here so the engine, the API, and the
self-correction loop share one implementation, but the originals are left in
place untouched.
"""
import datetime
import decimal
import hashlib
import re
from typing import Optional, Tuple

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

_FENCE_RE = re.compile(r"^```(?:sql)?\s*|\s*```$", re.IGNORECASE)
_LIMIT_TAIL_RE = re.compile(r"\bLIMIT\s+(\d+)\s*$", re.IGNORECASE)
_TOP_HEAD_RE = re.compile(r"^\s*SELECT\s+TOP\s+(\d+)\b", re.IGNORECASE)
_SQL_START_RE = re.compile(r"^\s*(WITH|SELECT)\b", re.IGNORECASE)


def clean_sql(sql: Optional[str]) -> Optional[str]:
    """Strip markdown fences, surrounding whitespace, and a trailing semicolon."""
    if sql is None:
        return None
    cleaned = sql.strip()
    if cleaned.startswith("```"):
        cleaned = _FENCE_RE.sub("", cleaned).strip()
    cleaned = cleaned.rstrip(";").strip()
    return cleaned


def fix_tsql_syntax(sql: Optional[str]) -> Optional[str]:
    """Convert a trailing ``LIMIT n`` to ``SELECT TOP n`` for SQL Server.

    Matches the benchmark's ``_fix_tsql`` behaviour so the default (bank DB)
    path is reproduced exactly.
    """
    if sql is None:
        return None
    cleaned = clean_sql(sql)
    match = _LIMIT_TAIL_RE.search(cleaned)
    if match:
        n = match.group(1)
        cleaned = _LIMIT_TAIL_RE.sub("", cleaned).strip()
        cleaned = re.sub(r"^SELECT\b", f"SELECT TOP {n}", cleaned, count=1, flags=re.IGNORECASE)
    return cleaned


def fix_standard_syntax(sql: Optional[str]) -> Optional[str]:
    """Convert a leading ``SELECT TOP n`` to ``... LIMIT n`` for SQLite/PostgreSQL.

    Used when an uploaded database is the active target instead of the bank DB.
    """
    if sql is None:
        return None
    cleaned = clean_sql(sql)
    match = _TOP_HEAD_RE.search(cleaned)
    if match:
        n = match.group(1)
        cleaned = re.sub(r"^(\s*SELECT)\s+TOP\s+\d+\b", r"\1", cleaned, count=1, flags=re.IGNORECASE).strip()
        cleaned = f"{cleaned} LIMIT {n}"
    return cleaned


def looks_like_sql(sql: Optional[str]) -> bool:
    """True if the text begins with WITH or SELECT.

    The LLM occasionally returns an explanation instead of SQL (Vanna's
    ``extract_sql`` passes such text through unchanged). Treating that as a
    fault lets the correction loop attempt a repair rather than executing prose.
    """
    if not sql or not sql.strip():
        return False
    return bool(_SQL_START_RE.match(sql))


def execute_sql(engine: Engine, sql: str) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """Execute read SQL and return ``(dataframe, error_string)``.

    Mirrors the benchmark executor: on success returns ``(df, None)``; on any
    exception returns ``(None, str(exception))``.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
            return df, None
    except Exception as exc:
        return None, str(exc)


def row_count(df: Optional[pd.DataFrame]) -> Optional[int]:
    if df is None:
        return None
    return int(len(df))


def _normalize_cell(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, decimal.Decimal):
        return format(value.normalize(), "f")
    return str(value).strip()


def result_signature(df: Optional[pd.DataFrame]) -> Optional[str]:
    """Order-independent signature of a result set.

    Rows are normalised to string tuples (ignoring column order and names) and
    sorted, so two queries that return the same rows in a different order or
    with reordered columns produce the same signature. Returns None when the
    query did not execute, and a distinct marker for an empty result set.

    This backs self-consistency voting (grouping candidates by what they return)
    and a stricter result comparison than raw equality.
    """
    if df is None:
        return None
    if df.empty:
        return "EMPTY"
    rows = []
    for _, row in df.iterrows():
        cells = sorted(_normalize_cell(v) for v in row.tolist())
        rows.append("\x1f".join(cells))
    rows.sort()
    payload = f"cols={len(df.columns)}\x1e" + "\x1e".join(rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_safe(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def df_to_records(df: Optional[pd.DataFrame], max_rows: int = 200) -> Tuple[list, list, bool]:
    """Return ``(columns, rows, truncated)`` with JSON-safe scalar values.

    ``rows`` is a list of row lists aligned to ``columns``. NaN/NaT become null,
    Decimal becomes float, and dates become ISO strings.
    """
    if df is None:
        return [], [], False
    columns = [str(c) for c in df.columns]
    truncated = len(df) > max_rows
    view = df.head(max_rows) if truncated else df
    rows = [[_json_safe(v) for v in record] for record in view.itertuples(index=False, name=None)]
    return columns, rows, truncated

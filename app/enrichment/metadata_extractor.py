"""Metadata Extractor for DB-Navigator AI Schema Enrichment Pipeline.

Stage 1 + Stage 2 of the enrichment pipeline:
  - Extracts structural metadata from a MS SQL Server schema via sys.* views
  - Extracts sample values, distinct counts, NULL percentages per column
  - Stores results in PostgreSQL public.enriched_tables / enriched_columns (UPSERT)

Dual-database architecture:
  - SOURCE (read-only): MS SQL Server (the undocumented bank database)
  - TARGET (read-write): PostgreSQL (app metadata, embeddings, logs)

Usage:
    from app.enrichment.metadata_extractor import MetadataExtractor

    extractor = MetadataExtractor(
        source_url="mssql+pyodbc://user:pass@server/db?driver=ODBC+Driver+17+for+SQL+Server",
        target_url="postgresql://dbnavigator:dbnavigator_dev@localhost:5432/dbnavigator",
    )
    stats = extractor.run(schema_name="bank")
    # stats = {"tables": 14, "columns": 131, "elapsed_sec": 2.3}

    # Dry run (extract from SQL Server, don't persist to PostgreSQL):
    tables, columns = extractor.extract(schema_name="bank")

    # Generate Vanna documentation strings:
    docs = extractor.format_for_vanna(schema_name="bank")

Design notes:
    - Schema-agnostic: works on any SQL Server schema, not hardcoded to bank
    - Batch-oriented: one query per metadata dimension, not N+1 per table/column
    - Idempotent: uses ON CONFLICT ... DO UPDATE for safe re-runs on PostgreSQL
    - Sample values capped at 5 distinct non-NULL values per column
    - Row counts use sys.dm_db_partition_stats for speed (no full table scans)
    - Generates T-SQL compatible queries throughout
    - Handles SQL Server column types that don't support COUNT(DISTINCT)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes for structured extraction output
# ---------------------------------------------------------------------------

@dataclass
class TableMeta:
    """Metadata for a single table."""
    schema_name: str
    table_name: str
    row_count: int
    column_count: int
    has_pk: bool
    index_names: list[str] = field(default_factory=list)


@dataclass
class ColumnMeta:
    """Metadata for a single column."""
    schema_name: str
    table_name: str
    column_name: str
    ordinal_position: int
    data_type: str
    is_nullable: bool
    character_max_length: Optional[int]
    numeric_precision: Optional[int]
    column_default: Optional[str]
    sample_values: list[str] = field(default_factory=list)
    distinct_count: int = 0
    null_count: int = 0
    null_pct: float = 0.0
    total_rows: int = 0


# ---------------------------------------------------------------------------
# Main extractor class
# ---------------------------------------------------------------------------

class MetadataExtractor:
    """Extracts metadata from MS SQL Server, persists to PostgreSQL.

    Covers subtasks 3.1 (metadata extraction) and 3.7 (sample value extraction)
    from the thesis project plan.
    """

    # Max distinct sample values to extract per column
    SAMPLE_LIMIT = 5

    def __init__(
        self,
        source_url: str,
        target_url: str,
        source_engine: Optional[Engine] = None,
        target_engine: Optional[Engine] = None,
    ):
        
        self._source = source_engine or create_engine(source_url)
        self._target = target_engine or create_engine(target_url)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, schema_name: str) -> tuple[list[TableMeta], list[ColumnMeta]]:
        
        logger.info("Starting metadata extraction for schema '%s'", schema_name)
        t0 = time.perf_counter()

        tables = self._extract_tables(schema_name)
        columns = self._extract_columns(schema_name, tables)

        elapsed = time.perf_counter() - t0
        logger.info(
            "Extraction complete: %d tables, %d columns in %.2fs",
            len(tables), len(columns), elapsed,
        )
        return tables, columns

    def run(self, schema_name: str) -> dict:
       
        t0 = time.perf_counter()
        tables, columns = self.extract(schema_name)
        self._persist_tables(tables)
        self._persist_columns(columns)
        elapsed = time.perf_counter() - t0

        summary = {
            "tables": len(tables),
            "columns": len(columns),
            "elapsed_sec": round(elapsed, 2),
        }
        logger.info("Metadata extraction + persist complete: %s", summary)
        return summary

    # ------------------------------------------------------------------
    # Extraction internals (all queries target MS SQL Server)
    # ------------------------------------------------------------------

    def _extract_tables(self, schema_name: str) -> list[TableMeta]:
        
        with self._source.connect() as conn:
            # --- 1. Tables + row counts (fast, from partition stats) ---
            rows = conn.execute(text("""
                SELECT
                    t.name AS table_name,
                    ISNULL(SUM(ps.row_count), 0) AS row_count
                FROM sys.tables t
                INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
                LEFT JOIN sys.dm_db_partition_stats ps
                    ON ps.object_id = t.object_id
                    AND ps.index_id IN (0, 1)
                WHERE s.name = :schema
                GROUP BY t.name
                ORDER BY t.name
            """), {"schema": schema_name}).fetchall()

            table_names = [r[0] for r in rows]
            row_counts = {r[0]: r[1] for r in rows}
            logger.info("Found %d tables in schema '%s'", len(table_names), schema_name)

            # --- 2. Column counts per table (single query) ---
            col_counts = {}
            if table_names:
                cc_rows = conn.execute(text("""
                    SELECT
                        t.name AS table_name,
                        COUNT(c.column_id) AS col_count
                    FROM sys.columns c
                    INNER JOIN sys.tables t ON c.object_id = t.object_id
                    INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
                    WHERE s.name = :schema
                    GROUP BY t.name
                """), {"schema": schema_name}).fetchall()
                col_counts = {r[0]: r[1] for r in cc_rows}

            # --- 3. Primary key detection (single query) ---
            pk_tables = set()
            if table_names:
                pk_rows = conn.execute(text("""
                    SELECT DISTINCT t.name AS table_name
                    FROM sys.indexes i
                    INNER JOIN sys.tables t ON i.object_id = t.object_id
                    INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
                    WHERE s.name = :schema
                        AND i.is_primary_key = 1
                """), {"schema": schema_name}).fetchall()
                pk_tables = {r[0] for r in pk_rows}

            # --- 4. Indexes per table (single query) ---
            index_map: dict[str, list[str]] = {tn: [] for tn in table_names}
            if table_names:
                idx_rows = conn.execute(text("""
                    SELECT
                        t.name AS table_name,
                        i.name AS index_name
                    FROM sys.indexes i
                    INNER JOIN sys.tables t ON i.object_id = t.object_id
                    INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
                    WHERE s.name = :schema
                        AND i.name IS NOT NULL
                    ORDER BY t.name, i.name
                """), {"schema": schema_name}).fetchall()
                for tbl, idx in idx_rows:
                    if tbl in index_map:
                        index_map[tbl].append(idx)

        # --- Build output ---
        tables = []
        for tn in table_names:
            tables.append(TableMeta(
                schema_name=schema_name,
                table_name=tn,
                row_count=row_counts.get(tn, 0),
                column_count=col_counts.get(tn, 0),
                has_pk=tn in pk_tables,
                index_names=index_map.get(tn, []),
            ))
        return tables

    def _extract_columns(
        self,
        schema_name: str,
        tables: list[TableMeta],
    ) -> list[ColumnMeta]:
        
        with self._source.connect() as conn:
            # --- 1. Base column metadata (single query for entire schema) ---
            col_rows = conn.execute(text("""
                SELECT
                    t.name AS table_name,
                    c.name AS column_name,
                    c.column_id AS ordinal_position,
                    tp.name AS data_type,
                    c.is_nullable,
                    c.max_length AS character_max_length,
                    c.precision AS numeric_precision,
                    dc.definition AS column_default
                FROM sys.columns c
                INNER JOIN sys.tables t ON c.object_id = t.object_id
                INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
                INNER JOIN sys.types tp ON c.user_type_id = tp.user_type_id
                LEFT JOIN sys.default_constraints dc ON c.default_object_id = dc.object_id
                WHERE s.name = :schema
                ORDER BY t.name, c.column_id
            """), {"schema": schema_name}).fetchall()

            # Group by table
            table_columns: dict[str, list] = {}
            for row in col_rows:
                tbl = row[0]
                if tbl not in table_columns:
                    table_columns[tbl] = []
                table_columns[tbl].append(row)

            # --- 2. Per-table: distinct counts, null counts, sample values ---
            all_columns: list[ColumnMeta] = []

            for tbl_meta in tables:
                tn = tbl_meta.table_name
                cols_for_table = table_columns.get(tn, [])
                if not cols_for_table:
                    continue

                col_names = [c[1] for c in cols_for_table]
                row_count = tbl_meta.row_count

                stats = self._extract_column_stats(
                    conn, schema_name, tn, col_names, row_count,
                )

                samples = self._extract_sample_values(
                    conn, schema_name, tn, col_names,
                )

                for row in cols_for_table:
                    (_, col_name, ordinal, dtype, nullable,
                     char_len, num_prec, col_default) = row

                    col_stats = stats.get(col_name, {})
                    dist = col_stats.get("distinct", 0)
                    nulls = col_stats.get("nulls", 0)
                    null_pct = round(
                        (nulls / row_count * 100), 2
                    ) if row_count > 0 else 0.0

                    all_columns.append(ColumnMeta(
                        schema_name=schema_name,
                        table_name=tn,
                        column_name=col_name,
                        ordinal_position=ordinal,
                        data_type=dtype,
                        is_nullable=bool(nullable),
                        character_max_length=char_len,
                        numeric_precision=num_prec,
                        column_default=col_default,
                        sample_values=samples.get(col_name, []),
                        distinct_count=dist,
                        null_count=nulls,
                        null_pct=null_pct,
                        total_rows=row_count,
                    ))

            logger.info("Extracted metadata for %d columns", len(all_columns))
            return all_columns

    def _extract_column_stats(
        self,
        conn,
        schema_name: str,
        table_name: str,
        col_names: list[str],
        row_count: int,
    ) -> dict[str, dict]:
        """Compute distinct count and null count for all columns in one scan.

        Generates T-SQL like:
            SELECT
                COUNT(DISTINCT [col1]) AS [dist__col1],
                SUM(CASE WHEN [col1] IS NULL THEN 1 ELSE 0 END) AS [null__col1],
                ...
            FROM [schema].[table]

        Falls back to per-column queries for types that don't support
        COUNT(DISTINCT) (text, ntext, image, xml, geography, geometry).
        """
        if row_count == 0 or not col_names:
            return {c: {"distinct": 0, "nulls": 0} for c in col_names}

        select_parts = []
        for c in col_names:
            safe = c.replace("]", "]]")
            select_parts.append(
                f'COUNT(DISTINCT [{safe}]) AS [dist__{safe}]'
            )
            select_parts.append(
                f'SUM(CASE WHEN [{safe}] IS NULL THEN 1 ELSE 0 END) AS [null__{safe}]'
            )

        query = (
            f"SELECT {', '.join(select_parts)} "
            f"FROM [{schema_name}].[{table_name}]"
        )

        try:
            row = conn.execute(text(query)).fetchone()
        except Exception as e:
            logger.warning(
                "Batch stats failed for %s.%s (%s), falling back per-column",
                schema_name, table_name, e,
            )
            return self._extract_column_stats_fallback(
                conn, schema_name, table_name, col_names, row_count,
            )

        if row is None:
            return {c: {"distinct": 0, "nulls": 0} for c in col_names}

        result = {}
        row_dict = row._mapping
        for c in col_names:
            safe = c.replace("]", "]]")
            result[c] = {
                "distinct": row_dict.get(f"dist__{safe}", 0) or 0,
                "nulls": row_dict.get(f"null__{safe}", 0) or 0,
            }
        return result

    def _extract_column_stats_fallback(
        self,
        conn,
        schema_name: str,
        table_name: str,
        col_names: list[str],
        row_count: int,
    ) -> dict[str, dict]:
        
        result = {}
        for c in col_names:
            safe = c.replace("]", "]]")
            try:
                row = conn.execute(text(
                    f"SELECT COUNT(DISTINCT [{safe}]) AS dist, "
                    f"SUM(CASE WHEN [{safe}] IS NULL THEN 1 ELSE 0 END) AS nulls "
                    f"FROM [{schema_name}].[{table_name}]"
                )).fetchone()
                result[c] = {
                    "distinct": row[0] if row else 0,
                    "nulls": row[1] if row else 0,
                }
            except Exception:
                try:
                    row = conn.execute(text(
                        f"SELECT SUM(CASE WHEN [{safe}] IS NULL THEN 1 ELSE 0 END) "
                        f"FROM [{schema_name}].[{table_name}]"
                    )).fetchone()
                    result[c] = {
                        "distinct": -1,
                        "nulls": row[0] if row else 0,
                    }
                except Exception:
                    result[c] = {"distinct": -1, "nulls": -1}

        return result

    def _extract_sample_values(
        self,
        conn,
        schema_name: str,
        table_name: str,
        col_names: list[str],
    ) -> dict[str, list[str]]:
        
        samples: dict[str, list[str]] = {}

        for c in col_names:
            safe = c.replace("]", "]]")
            query = (
                f"SELECT DISTINCT TOP ({self.SAMPLE_LIMIT}) "
                f"CAST([{safe}] AS NVARCHAR(500)) AS val "
                f"FROM [{schema_name}].[{table_name}] "
                f"WHERE [{safe}] IS NOT NULL"
            )
            try:
                rows = conn.execute(text(query)).fetchall()
                samples[c] = [r[0] for r in rows if r[0] is not None]
            except Exception as e:
                logger.warning(
                    "Could not sample %s.%s.%s: %s",
                    schema_name, table_name, c, e,
                )
                samples[c] = []

        return samples

    # ------------------------------------------------------------------
    # Persistence (all writes go to PostgreSQL)
    # ------------------------------------------------------------------

    def _persist_tables(self, tables: list[TableMeta]) -> None:
        if not tables:
            return

        with self._target.begin() as conn:
            for tbl in tables:
                conn.execute(text("""
                    INSERT INTO public.enriched_tables
                        (schema_name, table_name, row_count, column_count,
                         has_pk, enrichment_model, enriched_at)
                    VALUES
                        (:schema, :table, :rows, :cols,
                         :pk, 'metadata_extractor', CURRENT_TIMESTAMP)
                    ON CONFLICT (schema_name, table_name) DO UPDATE SET
                        row_count = EXCLUDED.row_count,
                        column_count = EXCLUDED.column_count,
                        has_pk = EXCLUDED.has_pk,
                        enrichment_model = EXCLUDED.enrichment_model,
                        enriched_at = CURRENT_TIMESTAMP
                """), {
                    "schema": tbl.schema_name,
                    "table": tbl.table_name,
                    "rows": tbl.row_count,
                    "cols": tbl.column_count,
                    "pk": tbl.has_pk,
                })

        logger.info("Persisted %d table records to enriched_tables", len(tables))

    def _persist_columns(self, columns: list[ColumnMeta]) -> None:
        if not columns:
            return

        with self._target.begin() as conn:
            for col in columns:
                conn.execute(text("""
                    INSERT INTO public.enriched_columns
                        (schema_name, table_name, column_name, data_type,
                         is_nullable, sample_values, distinct_count, null_pct,
                         enriched_at)
                    VALUES
                        (:schema, :table, :col, :dtype,
                         :nullable, :samples, :distinct, :null_pct,
                         CURRENT_TIMESTAMP)
                    ON CONFLICT (schema_name, table_name, column_name) DO UPDATE SET
                        data_type = EXCLUDED.data_type,
                        is_nullable = EXCLUDED.is_nullable,
                        sample_values = EXCLUDED.sample_values,
                        distinct_count = EXCLUDED.distinct_count,
                        null_pct = EXCLUDED.null_pct,
                        enriched_at = CURRENT_TIMESTAMP
                """), {
                    "schema": col.schema_name,
                    "table": col.table_name,
                    "col": col.column_name,
                    "dtype": col.data_type,
                    "nullable": col.is_nullable,
                    "samples": col.sample_values,
                    "distinct": col.distinct_count,
                    "null_pct": col.null_pct,
                })

        logger.info("Persisted %d column records to enriched_columns", len(columns))

    # ------------------------------------------------------------------
    # Utility / inspection
    # ------------------------------------------------------------------

    def summary(self, schema_name: str) -> str:
        tables, columns = self.extract(schema_name)

        lines = [
            f"Schema Metadata Summary: {schema_name}",
            f"{'=' * 50}",
            f"Tables: {len(tables)}",
            f"Total columns: {len(columns)}",
            "",
        ]

        for tbl in tables:
            tbl_cols = [c for c in columns if c.table_name == tbl.table_name]
            lines.append(f"  {tbl.table_name}")
            lines.append(
                f"    Rows: {tbl.row_count:,} | Columns: {tbl.column_count} | "
                f"PK: {'yes' if tbl.has_pk else 'NO'} | "
                f"Indexes: {len(tbl.index_names)}"
            )
            for col in tbl_cols:
                sv = ", ".join(col.sample_values[:3])
                if len(col.sample_values) > 3:
                    sv += ", ..."
                lines.append(
                    f"    - {col.column_name} ({col.data_type}) | "
                    f"distinct: {col.distinct_count} | "
                    f"nulls: {col.null_pct}% | "
                    f"samples: [{sv}]"
                )
            lines.append("")

        return "\n".join(lines)

    def format_for_vanna(self, schema_name: str) -> list[str]:
        
        tables, columns = self.extract(schema_name)
        docs = []

        for tbl in tables:
            tbl_cols = [
                c for c in columns if c.table_name == tbl.table_name
            ]
            tbl_cols.sort(key=lambda c: c.ordinal_position)

            parts = [
                f"Table [{schema_name}].[{tbl.table_name}] "
                f"({tbl.row_count:,} rows, {tbl.column_count} columns):",
            ]

            for col in tbl_cols:
                sv_str = ""
                if col.sample_values:
                    sv_str = f" Sample values: {', '.join(col.sample_values)}."
                null_str = ""
                if col.null_pct > 0:
                    null_str = f" {col.null_pct}% NULL."

                parts.append(
                    f"  - [{col.column_name}] ({col.data_type}): "
                    f"{col.distinct_count} distinct values.{null_str}{sv_str}"
                )

            docs.append("\n".join(parts))

        return docs

    def format_ddl_for_vanna(self, schema_name: str) -> list[str]:
        
        tables, columns = self.extract(schema_name)
        ddls = []

        for tbl in tables:
            tbl_cols = [
                c for c in columns if c.table_name == tbl.table_name
            ]
            tbl_cols.sort(key=lambda c: c.ordinal_position)

            lines = [f"CREATE TABLE [{schema_name}].[{tbl.table_name}] ("]
            for i, col in enumerate(tbl_cols):
                type_str = col.data_type.upper()
                if col.character_max_length and col.character_max_length > 0:
                    if col.character_max_length == -1:
                        type_str += "(MAX)"
                    else:
                        type_str += f"({col.character_max_length})"
                elif col.numeric_precision and col.data_type not in (
                    "int", "bigint", "smallint", "tinyint", "bit",
                    "money", "smallmoney", "float", "real",
                ):
                    type_str += f"({col.numeric_precision})"

                null_str = "" if col.is_nullable else " NOT NULL"
                comma = "," if i < len(tbl_cols) - 1 else ""
                lines.append(f"    [{col.column_name}] {type_str}{null_str}{comma}")

            lines.append(");")
            ddls.append("\n".join(lines))

        return ddls


# ---------------------------------------------------------------------------
# CLI entry point for standalone testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        from config import SOURCE_DATABASE_URL, DATABASE_URL, BANK_SCHEMA
    except ImportError:
        SOURCE_DATABASE_URL = sys.argv[1] if len(sys.argv) > 1 else (
            "mssql+pyodbc://sa:YourPassword@localhost/bankdb"
            "?driver=ODBC+Driver+17+for+SQL+Server"
        )
        DATABASE_URL = sys.argv[2] if len(sys.argv) > 2 else (
            "postgresql://dbnavigator:dbnavigator_dev@localhost:5432/dbnavigator"
        )
        BANK_SCHEMA = sys.argv[3] if len(sys.argv) > 3 else "bank"

    extractor = MetadataExtractor(
        source_url=SOURCE_DATABASE_URL,
        target_url=DATABASE_URL,
    )

    if "--dry-run" in sys.argv:
        print(extractor.summary(BANK_SCHEMA))
    elif "--vanna" in sys.argv:
        docs = extractor.format_for_vanna(BANK_SCHEMA)
        for doc in docs:
            print(doc)
            print()
    elif "--ddl" in sys.argv:
        ddls = extractor.format_ddl_for_vanna(BANK_SCHEMA)
        for ddl in ddls:
            print(ddl)
            print()
    else:
        stats = extractor.run(BANK_SCHEMA)
        print(f"Done: {stats}")
        print()
        print(extractor.summary(BANK_SCHEMA))
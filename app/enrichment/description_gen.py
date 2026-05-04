"""LLM Description Generator for DB-Navigator AI Schema Enrichment Pipeline.

Stage 4 of the enrichment pipeline:
  - Generates natural language descriptions for tables and columns
  - Uses metadata extractor output (sample values, stats) as input context
  - Sends schema structure + sample data to GPT-4o-mini
  - Stores descriptions in PostgreSQL enriched_tables/enriched_columns

Architecture:
  - SOURCE: MS SQL Server or PostgreSQL (bank database, for sample rows)
  - TARGET: PostgreSQL (enriched_tables.description, enriched_columns.description)
  - LLM: OpenAI GPT-4o-mini (configurable)

Usage:
    from app.enrichment.description_gen import DescriptionGenerator

    gen = DescriptionGenerator(
        source_url="mssql+pyodbc://...",
        target_url="postgresql://...",
        api_key="sk-...",
        dialect="mssql",
    )

    # Generate and persist descriptions
    stats = gen.run(schema_name="bank")

    # Dry run (print without persisting)
    gen.dry_run(schema_name="bank")

    # Generate Vanna documentation strings
    docs = gen.format_for_vanna(schema_name="bank")

Design notes:
    - Batch processing: one LLM call per table (table + all its columns together)
    - Avoids sending PII: uses column names, types, and sample values only
    - Configurable column exclusion list for sensitive columns
    - Rate limiting: 0.5s delay between API calls to avoid throttling
    - Provenance tracking: records model name and timestamp for each description
    - Idempotent: updates existing descriptions on re-run
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from openai import OpenAI
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Column name patterns to exclude from sample value display in prompts
# (columns likely containing PII)
# ---------------------------------------------------------------------------

SENSITIVE_PATTERNS = frozenset({
    "name", "nm", "surnm", "phone", "email", "addr", "address",
    "idnp", "idno", "ssn", "passport", "birth",
})


def _is_sensitive_column(col_name: str) -> bool:
    """Check if a column name matches sensitive PII patterns."""
    lower = col_name.lower()
    return any(pat in lower for pat in SENSITIVE_PATTERNS)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TableDescription:
    """Generated description for a table."""
    schema_name: str
    table_name: str
    description: str
    model: str
    column_descriptions: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main generator class
# ---------------------------------------------------------------------------

class DescriptionGenerator:
    """Generates LLM-based descriptions for tables and columns.

    Covers subtasks 3.5 (table descriptions) and 3.6 (column descriptions)
    from the thesis project plan.
    """

    DEFAULT_MODEL = "gpt-4o-mini"
    SAMPLE_ROWS = 5
    DELAY_BETWEEN_CALLS = 0.5  # seconds

    def __init__(
        self,
        source_url: str,
        target_url: str,
        api_key: str,
        model: str = DEFAULT_MODEL,
        dialect: str = "postgresql",
        source_engine: Optional[Engine] = None,
        target_engine: Optional[Engine] = None,
    ):
        self._source = source_engine or create_engine(source_url)
        self._target = target_engine or create_engine(target_url)
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._dialect = dialect.lower()

    def _q(self, identifier: str) -> str:
        if self._dialect == "mssql":
            return f"[{identifier.replace(']', ']]')}]"
        else:
            return f'"{identifier.replace(chr(34), chr(34)+chr(34))}"'

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, schema_name: str) -> dict:
        """Generate descriptions and persist to PostgreSQL.

        Returns:
            Summary dict with tables processed, columns described, elapsed time.
        """
        t0 = time.perf_counter()

        descriptions = self._generate_all(schema_name)
        self._persist(descriptions)

        elapsed = time.perf_counter() - t0
        total_cols = sum(len(d.column_descriptions) for d in descriptions)

        summary = {
            "tables": len(descriptions),
            "columns": total_cols,
            "model": self._model,
            "elapsed_sec": round(elapsed, 2),
        }
        logger.info("Description generation complete: %s", summary)
        return summary

    def dry_run(self, schema_name: str) -> list[TableDescription]:
        """Generate descriptions and print them without persisting."""
        descriptions = self._generate_all(schema_name)

        for desc in descriptions:
            print(f"\n{'='*60}")
            print(f"Table: {schema_name}.{desc.table_name}")
            print(f"Description: {desc.description}")
            print(f"Columns:")
            for col_name, col_desc in desc.column_descriptions.items():
                print(f"  - {col_name}: {col_desc}")

        return descriptions

    def format_for_vanna(self, schema_name: str) -> list[str]:
        """Generate Vanna documentation strings from LLM descriptions.

        Returns:
            List of documentation strings, one per table.
        """
        descriptions = self._generate_all(schema_name)
        docs = []

        for desc in descriptions:
            parts = [
                f"Table {schema_name}.{desc.table_name}: {desc.description}",
                "Column descriptions:",
            ]
            for col_name, col_desc in desc.column_descriptions.items():
                parts.append(f"  - {col_name}: {col_desc}")

            docs.append("\n".join(parts))

        return docs

    # ------------------------------------------------------------------
    # Internal: generation
    # ------------------------------------------------------------------

    def _generate_all(self, schema_name: str) -> list[TableDescription]:
        """Generate descriptions for all tables in the schema."""
        tables_meta = self._get_tables_and_columns(schema_name)

        descriptions = []
        for i, (table_name, columns) in enumerate(tables_meta.items()):
            logger.info(
                "Generating descriptions for %s.%s (%d/%d)",
                schema_name, table_name, i + 1, len(tables_meta),
            )

            sample_rows = self._get_sample_rows(schema_name, table_name)
            desc = self._generate_for_table(
                schema_name, table_name, columns, sample_rows,
            )
            descriptions.append(desc)

            if i < len(tables_meta) - 1:
                time.sleep(self.DELAY_BETWEEN_CALLS)

        return descriptions

    def _generate_for_table(
        self,
        schema_name: str,
        table_name: str,
        columns: list[dict],
        sample_rows: list[dict],
    ) -> TableDescription:
        """Generate descriptions for one table and all its columns in a single LLM call."""

        # Build column info section
        col_info_lines = []
        for col in columns:
            line = f"- {col['name']} ({col['type']}"
            if col.get('nullable'):
                line += ", nullable"
            line += f"): {col['distinct_count']} distinct values"
            if col['null_pct'] > 0:
                line += f", {col['null_pct']}% NULL"
            if col.get('sample_values') and not _is_sensitive_column(col['name']):
                sv = ", ".join(str(v) for v in col['sample_values'][:5])
                line += f". Sample values: {sv}"
            elif _is_sensitive_column(col['name']):
                line += ". [PII column - sample values excluded]"
            col_info_lines.append(line)

        col_info = "\n".join(col_info_lines)

        # Build sample rows section
        sample_section = ""
        if sample_rows:
            # Filter out sensitive columns from sample display
            safe_cols = [
                c['name'] for c in columns
                if not _is_sensitive_column(c['name'])
            ]
            if safe_cols:
                filtered_rows = []
                for row in sample_rows[:self.SAMPLE_ROWS]:
                    filtered = {k: v for k, v in row.items() if k in safe_cols}
                    filtered_rows.append(filtered)
                sample_section = f"\nSample rows (sensitive columns excluded):\n{json.dumps(filtered_rows, indent=2, default=str)}"

        prompt = f"""You are a database documentation expert. Given the following table metadata and sample data from a banking database, generate:

1. A concise business description of what this table stores and its purpose (1-2 sentences).
2. A one-sentence description for each column explaining what it represents.

Table: {schema_name}.{table_name}

Columns:
{col_info}
{sample_section}

Respond in this exact JSON format (no markdown, no backticks):
{{
  "table_description": "...",
  "columns": {{
    "column_name": "description",
    ...
  }}
}}

Be concise and specific. Use banking domain terminology where appropriate. Focus on what each column represents in business terms, not just its technical properties."""

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2000,
            )

            content = response.choices[0].message.content.strip()
            # Strip markdown fences if present
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            result = json.loads(content)

            return TableDescription(
                schema_name=schema_name,
                table_name=table_name,
                description=result.get("table_description", ""),
                model=self._model,
                column_descriptions=result.get("columns", {}),
            )

        except json.JSONDecodeError as e:
            logger.warning(
                "JSON parse error for %s.%s: %s. Raw: %s",
                schema_name, table_name, e, content[:200],
            )
            return TableDescription(
                schema_name=schema_name,
                table_name=table_name,
                description=f"[Generation failed: JSON parse error]",
                model=self._model,
            )
        except Exception as e:
            logger.warning(
                "LLM call failed for %s.%s: %s",
                schema_name, table_name, e,
            )
            return TableDescription(
                schema_name=schema_name,
                table_name=table_name,
                description=f"[Generation failed: {e}]",
                model=self._model,
            )

    # ------------------------------------------------------------------
    # Internal: metadata queries
    # ------------------------------------------------------------------

    def _get_tables_and_columns(self, schema_name: str) -> dict[str, list[dict]]:
        """Get all tables and their column metadata from PostgreSQL enrichment tables.

        Falls back to INFORMATION_SCHEMA if enrichment tables are empty.
        """
        result: dict[str, list[dict]] = {}

        # Try enriched data first (has sample values and stats)
        with self._target.connect() as conn:
            rows = conn.execute(text("""
                SELECT table_name, column_name, data_type, is_nullable,
                       sample_values, distinct_count, null_pct
                FROM public.enriched_columns
                WHERE schema_name = :schema
                ORDER BY table_name, column_name
            """), {"schema": schema_name}).fetchall()

        if rows:
            for row in rows:
                tbl = row[0]
                if tbl not in result:
                    result[tbl] = []
                result[tbl].append({
                    "name": row[1],
                    "type": row[2],
                    "nullable": row[3],
                    "sample_values": row[4] if row[4] else [],
                    "distinct_count": row[5] or 0,
                    "null_pct": float(row[6]) if row[6] else 0.0,
                })
            logger.info("Loaded enriched metadata for %d tables", len(result))
            return result

        # Fallback: query source database directly
        logger.info("No enriched data found, querying source database directly")
        with self._source.connect() as conn:
            if self._dialect == "mssql":
                rows = conn.execute(text("""
                    SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE,
                           CASE WHEN IS_NULLABLE='YES' THEN 1 ELSE 0 END
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = :schema
                    ORDER BY TABLE_NAME, ORDINAL_POSITION
                """), {"schema": schema_name}).fetchall()
            else:
                rows = conn.execute(text("""
                    SELECT table_name, column_name, udt_name,
                           CASE WHEN is_nullable='YES' THEN true ELSE false END
                    FROM information_schema.columns
                    WHERE table_schema = :schema
                    ORDER BY table_name, ordinal_position
                """), {"schema": schema_name}).fetchall()

            for row in rows:
                tbl = row[0]
                if tbl not in result:
                    result[tbl] = []
                result[tbl].append({
                    "name": row[1],
                    "type": row[2],
                    "nullable": bool(row[3]),
                    "sample_values": [],
                    "distinct_count": 0,
                    "null_pct": 0.0,
                })

        return result

    def _get_sample_rows(
        self,
        schema_name: str,
        table_name: str,
    ) -> list[dict]:
        """Get a few sample rows from the source database."""
        sq = self._q(schema_name)
        st = self._q(table_name)

        if self._dialect == "mssql":
            query = f"SELECT TOP {self.SAMPLE_ROWS} * FROM {sq}.{st}"
        else:
            query = f"SELECT * FROM {sq}.{st} LIMIT {self.SAMPLE_ROWS}"

        try:
            with self._source.connect() as conn:
                result = conn.execute(text(query))
                columns = list(result.keys())
                rows = []
                for row in result.fetchall():
                    rows.append(dict(zip(columns, row)))
                return rows
        except Exception as e:
            logger.warning("Could not fetch sample rows for %s.%s: %s",
                          schema_name, table_name, e)
            return []

    # ------------------------------------------------------------------
    # Persistence (writes to PostgreSQL)
    # ------------------------------------------------------------------

    def _persist(self, descriptions: list[TableDescription]) -> None:
        """Update enriched_tables and enriched_columns with generated descriptions."""
        if not descriptions:
            return

        with self._target.begin() as conn:
            for desc in descriptions:
                # Update table description
                conn.execute(text("""
                    UPDATE public.enriched_tables
                    SET description = :desc,
                        enrichment_model = :model,
                        enriched_at = CURRENT_TIMESTAMP
                    WHERE schema_name = :schema
                        AND table_name = :table
                """), {
                    "desc": desc.description,
                    "model": desc.model,
                    "schema": desc.schema_name,
                    "table": desc.table_name,
                })

                # Update column descriptions
                for col_name, col_desc in desc.column_descriptions.items():
                    conn.execute(text("""
                        UPDATE public.enriched_columns
                        SET description = :desc,
                            enriched_at = CURRENT_TIMESTAMP
                        WHERE schema_name = :schema
                            AND table_name = :table
                            AND column_name = :col
                    """), {
                        "desc": col_desc,
                        "schema": desc.schema_name,
                        "table": desc.table_name,
                        "col": col_name,
                    })

        total_cols = sum(len(d.column_descriptions) for d in descriptions)
        logger.info(
            "Persisted descriptions: %d tables, %d columns",
            len(descriptions), total_cols,
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def estimate_cost(self, schema_name: str) -> dict:
        """Estimate API cost before running.

        Returns:
            Dict with estimated tokens, calls, and cost.
        """
        tables_meta = self._get_tables_and_columns(schema_name)
        num_tables = len(tables_meta)
        avg_cols = sum(len(cols) for cols in tables_meta.values()) / max(num_tables, 1)

        # Rough estimates: ~500 tokens input + ~300 tokens output per table
        est_input_tokens = num_tables * 500
        est_output_tokens = num_tables * 300

        # GPT-4o-mini pricing: $0.15/M input, $0.60/M output
        cost_input = est_input_tokens / 1_000_000 * 0.15
        cost_output = est_output_tokens / 1_000_000 * 0.60

        return {
            "tables": num_tables,
            "avg_columns_per_table": round(avg_cols, 1),
            "est_input_tokens": est_input_tokens,
            "est_output_tokens": est_output_tokens,
            "est_cost_usd": round(cost_input + cost_output, 4),
            "est_time_sec": round(num_tables * (1.5 + self.DELAY_BETWEEN_CALLS), 1),
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        from config import SOURCE_DATABASE_URL, DATABASE_URL, OPENAI_API_KEY, BANK_SCHEMA
        default_source = SOURCE_DATABASE_URL
        default_target = DATABASE_URL
        default_key = OPENAI_API_KEY
        default_schema = BANK_SCHEMA
        default_dialect = "mssql" if "mssql" in SOURCE_DATABASE_URL else "postgresql"
    except ImportError:
        default_source = sys.argv[1] if len(sys.argv) > 1 else ""
        default_target = sys.argv[2] if len(sys.argv) > 2 else ""
        default_key = sys.argv[3] if len(sys.argv) > 3 else ""
        default_schema = sys.argv[4] if len(sys.argv) > 4 else "bank"
        default_dialect = sys.argv[5] if len(sys.argv) > 5 else "postgresql"

    if not default_key:
        print("Error: OPENAI_API_KEY not set. Set it in .env or pass as argument.")
        sys.exit(1)

    gen = DescriptionGenerator(
        source_url=default_source,
        target_url=default_target,
        api_key=default_key,
        dialect=default_dialect,
    )

    if "--estimate" in sys.argv:
        est = gen.estimate_cost(default_schema)
        print(f"Cost estimate for schema '{default_schema}':")
        print(f"  Tables: {est['tables']}")
        print(f"  Avg columns/table: {est['avg_columns_per_table']}")
        print(f"  Est. input tokens: {est['est_input_tokens']:,}")
        print(f"  Est. output tokens: {est['est_output_tokens']:,}")
        print(f"  Est. cost: ${est['est_cost_usd']}")
        print(f"  Est. time: {est['est_time_sec']}s")
    elif "--dry-run" in sys.argv:
        gen.dry_run(default_schema)
    elif "--vanna" in sys.argv:
        docs = gen.format_for_vanna(default_schema)
        for doc in docs:
            print(doc)
            print()
    else:
        stats = gen.run(default_schema)
        print(f"Done: {stats}")
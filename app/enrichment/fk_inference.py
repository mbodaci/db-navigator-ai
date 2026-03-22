"""Foreign Key Inference for DB-Navigator AI Schema Enrichment Pipeline.

Stage 3 of the enrichment pipeline:
  - Stage 1: Name-based pattern matching against PK columns
  - Stage 2: Inclusion dependency validation via data profiling
  - Built-in evaluation against known ground truth (precision/recall)

Architecture:
  - SOURCE: Database containing the bank schema (PostgreSQL or SQL Server)
  - TARGET: PostgreSQL (inferred_fks table for persistence)

Usage:
    from app.enrichment.fk_inference import FKInference

    fk = FKInference(
        source_url="postgresql://dbnavigator:dbnavigator_dev@localhost:5432/dbnavigator",
        target_url="postgresql://dbnavigator:dbnavigator_dev@localhost:5432/dbnavigator",
        dialect="postgresql",  # or "mssql"
    )

    # Stage 1 only (fast, no data queries)
    candidates = fk.stage1_name_matching("bank")

    # Stage 1 + Stage 2 (runs validation queries against source)
    validated = fk.run("bank")

    # Evaluate against ground truth
    report = fk.evaluate("bank", ground_truth=SYNTHETIC_DB_GROUND_TRUTH)

Design notes:
    - Dialect-agnostic: works on PostgreSQL (synthetic DB) and SQL Server (real bank)
    - Stage 1 uses two matching strategies: exact PK name match and suffix match
    - Stage 2 checks inclusion dependency, cardinality ratio, NULL rate
    - Confidence scores: 0.5 (suffix match) -> 0.7 (exact match) -> 0.9+ (validated)
    - Self-referencing FKs supported (e.g., tbl_emp.mgr_emp_no -> tbl_emp.emp_no)
    - Persists to public.inferred_fks via UPSERT
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ground truth for the synthetic bank database (22 known FKs)
# ---------------------------------------------------------------------------

SYNTHETIC_DB_GROUND_TRUTH: list[tuple[str, str, str, str]] = [
    # (src_table, src_column, tgt_table, tgt_column)
    ("tbl_emp", "br_cd", "tbl_br", "br_cd"),
    ("tbl_emp", "mgr_emp_no", "tbl_emp", "emp_no"),
    ("tbl_br", "br_mgr_emp_no", "tbl_emp", "emp_no"),
    ("tbl_cust", "br_cd", "tbl_br", "br_cd"),
    ("tbl_cust_addr", "cust_no", "tbl_cust", "cust_no"),
    ("tbl_acct", "cust_no", "tbl_cust", "cust_no"),
    ("tbl_acct", "acct_tp_cd", "tbl_acct_tp", "acct_tp_cd"),
    ("tbl_acct", "br_cd", "tbl_br", "br_cd"),
    ("tbl_txn", "acct_no", "tbl_acct", "acct_no"),
    ("tbl_txn", "txn_tp_cd", "tbl_txn_tp", "txn_tp_cd"),
    ("tbl_txn", "auth_emp_no", "tbl_emp", "emp_no"),
    ("tbl_loan", "cust_no", "tbl_cust", "cust_no"),
    ("tbl_loan", "prod_cd", "tbl_loan_prod", "prod_cd"),
    ("tbl_loan", "disb_acct_no", "tbl_acct", "acct_no"),
    ("tbl_loan", "repay_acct_no", "tbl_acct", "acct_no"),
    ("tbl_loan", "br_cd", "tbl_br", "br_cd"),
    ("tbl_loan", "loan_off_emp_no", "tbl_emp", "emp_no"),
    ("tbl_coll", "loan_no", "tbl_loan", "loan_no"),
    ("tbl_guar", "loan_no", "tbl_loan", "loan_no"),
    ("tbl_guar", "guar_cust_no", "tbl_cust", "cust_no"),
    ("tbl_card", "acct_no", "tbl_acct", "acct_no"),
    ("tbl_card", "cust_no", "tbl_cust", "cust_no"),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FKCandidate:
    """A candidate foreign key relationship."""
    src_table: str
    src_column: str
    tgt_table: str
    tgt_column: str
    match_type: str           # "exact" or "suffix"
    confidence: float         # 0.0 - 1.0
    inference_method: str     # "name_match" or "inclusion_dep"
    # Stage 2 validation fields (populated after validation)
    inclusion_pct: Optional[float] = None    # % of FK values found in PK
    cardinality_ratio: Optional[float] = None  # FK distinct / PK distinct
    fk_null_pct: Optional[float] = None      # % of NULLs in FK column
    violation_count: Optional[int] = None    # values in FK not in PK
    validated: bool = False


# ---------------------------------------------------------------------------
# Main inference class
# ---------------------------------------------------------------------------

class FKInference:
    """Infers foreign key relationships from an undocumented database.

    Covers subtasks 3.2 (name-based matching), 3.3 (inclusion dependency),
    and 3.4 (evaluation) from the thesis project plan.
    """

    # Confidence scores for different match types
    CONF_EXACT = 0.70       # Column name exactly matches a PK in another table
    CONF_SUFFIX = 0.50      # Column name ends with a PK column name
    CONF_VALIDATED = 0.95   # Stage 2: 100% inclusion dependency confirmed
    CONF_PARTIAL = 0.70     # Stage 2: >95% inclusion
    CONF_WEAK = 0.30        # Stage 2: <90% inclusion (likely false positive)

    # Columns to skip even if they match PK names (too generic, not FKs)
    SKIP_COLUMNS = frozenset({
        # These are the table's own PK - not an FK to another table
        # (handled dynamically, not here)
    })

    def __init__(
        self,
        source_url: str,
        target_url: str,
        dialect: str = "postgresql",
        source_engine: Optional[Engine] = None,
        target_engine: Optional[Engine] = None,
    ):
        """Initialize with connection URLs and SQL dialect.

        Args:
            source_url: Connection string for the bank database.
            target_url: Connection string for PostgreSQL (enrichment metadata).
            dialect: "postgresql" or "mssql" - controls identifier quoting and
                     query syntax differences.
            source_engine: Optional pre-existing engine for source DB.
            target_engine: Optional pre-existing engine for PostgreSQL.
        """
        self._source = source_engine or create_engine(source_url)
        self._target = target_engine or create_engine(target_url)
        self._dialect = dialect.lower()

        if self._dialect not in ("postgresql", "mssql"):
            raise ValueError(f"Unsupported dialect: {dialect}. Use 'postgresql' or 'mssql'.")

    # ------------------------------------------------------------------
    # Identifier quoting helper
    # ------------------------------------------------------------------

    def _q(self, identifier: str) -> str:
        """Quote an identifier for the current dialect.

        PostgreSQL: "identifier"
        SQL Server: [identifier]
        """
        if self._dialect == "mssql":
            safe = identifier.replace("]", "]]")
            return f"[{safe}]"
        else:
            safe = identifier.replace('"', '""')
            return f'"{safe}"'

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def stage1_name_matching(self, schema_name: str) -> list[FKCandidate]:
        """Stage 1: Identify FK candidates by matching column names to PKs.

        Strategy:
        1. Collect all primary key columns across all tables
        2. For each non-PK column in every table, check:
           a) Exact match: column name == PK column name in another table
           b) Suffix match: column name ends with a PK column name
              (catches aliased refs like disb_acct_no -> acct_no)
        3. Filter by data type compatibility
        4. Assign confidence scores

        Returns:
            List of FKCandidate objects with match_type and confidence.
        """
        logger.info("Stage 1: Name-based FK inference for schema '%s'", schema_name)

        with self._source.connect() as conn:
            # --- 1. Get all PK columns ---
            pk_map = self._get_primary_keys(conn, schema_name)
            logger.info("Found PKs in %d tables", len(pk_map))

            # --- 2. Get all columns with their types ---
            all_columns = self._get_all_columns(conn, schema_name)

        # --- 3. Build lookup: pk_column_name -> list of (table, column, type) ---
        pk_lookup: dict[str, list[tuple[str, str, str]]] = {}
        for table, pk_cols in pk_map.items():
            for pk_col, pk_type in pk_cols:
                if pk_col not in pk_lookup:
                    pk_lookup[pk_col] = []
                pk_lookup[pk_col].append((table, pk_col, pk_type))

        # --- 4. Scan all columns for matches ---
        candidates: list[FKCandidate] = []
        pk_columns_per_table = {
            t: {col for col, _ in cols} for t, cols in pk_map.items()
        }

        for src_table, src_col, src_type in all_columns:
            # Skip if this column IS the PK of its own table
            if src_col in pk_columns_per_table.get(src_table, set()):
                continue

            # --- 4a. Exact match ---
            if src_col in pk_lookup:
                for tgt_table, tgt_col, tgt_type in pk_lookup[src_col]:
                    # Allow self-referencing (same table) but not same column
                    if src_table == tgt_table and src_col == tgt_col:
                        continue
                    if not self._types_compatible(src_type, tgt_type):
                        continue
                    candidates.append(FKCandidate(
                        src_table=src_table,
                        src_column=src_col,
                        tgt_table=tgt_table,
                        tgt_column=tgt_col,
                        match_type="exact",
                        confidence=self.CONF_EXACT,
                        inference_method="name_match",
                    ))

            # --- 4b. Suffix match (only if no exact match was found) ---
            exact_targets = {
                (c.tgt_table, c.tgt_column) for c in candidates
                if c.src_table == src_table and c.src_column == src_col
            }

            for pk_name, pk_entries in pk_lookup.items():
                # Check if src_col ends with _pk_name (with underscore separator)
                # e.g., disb_acct_no ends with _acct_no, auth_emp_no ends with _emp_no
                if src_col == pk_name:
                    continue  # already handled by exact match
                if not src_col.endswith(f"_{pk_name}") and not src_col.endswith(pk_name):
                    continue
                # Require underscore separator to avoid partial matches
                # e.g., "cust_no" should not match "acust_no" without underscore
                prefix_end = len(src_col) - len(pk_name)
                if prefix_end > 0 and src_col[prefix_end - 1] != '_':
                    continue

                for tgt_table, tgt_col, tgt_type in pk_entries:
                    if (tgt_table, tgt_col) in exact_targets:
                        continue  # don't duplicate
                    if src_table == tgt_table and src_col == tgt_col:
                        continue
                    if not self._types_compatible(src_type, tgt_type):
                        continue
                    candidates.append(FKCandidate(
                        src_table=src_table,
                        src_column=src_col,
                        tgt_table=tgt_table,
                        tgt_column=tgt_col,
                        match_type="suffix",
                        confidence=self.CONF_SUFFIX,
                        inference_method="name_match",
                    ))

        logger.info("Stage 1 found %d FK candidates", len(candidates))
        return candidates

    def stage2_validate(
        self,
        schema_name: str,
        candidates: list[FKCandidate],
    ) -> list[FKCandidate]:
        """Stage 2: Validate candidates via inclusion dependency checks.

        For each candidate:
        1. Count values in FK column that don't exist in PK column
        2. Compute cardinality ratio (FK distinct / PK distinct)
        3. Compute NULL percentage in FK column
        4. Update confidence based on results

        Returns:
            Same candidates list with validation fields populated and
            confidence scores adjusted.
        """
        logger.info("Stage 2: Validating %d candidates via inclusion dependency", len(candidates))

        with self._source.connect() as conn:
            for i, cand in enumerate(candidates):
                try:
                    self._validate_candidate(conn, schema_name, cand)
                except Exception as e:
                    logger.warning(
                        "Validation failed for %s.%s -> %s.%s: %s",
                        cand.src_table, cand.src_column,
                        cand.tgt_table, cand.tgt_column, e,
                    )
                    cand.confidence = self.CONF_WEAK
                    cand.validated = False

                if (i + 1) % 10 == 0:
                    logger.info("  Validated %d / %d candidates", i + 1, len(candidates))

        # Sort by confidence descending
        candidates.sort(key=lambda c: c.confidence, reverse=True)

        validated_count = sum(1 for c in candidates if c.validated)
        logger.info(
            "Stage 2 complete: %d / %d candidates validated",
            validated_count, len(candidates),
        )
        return candidates

    def run(self, schema_name: str) -> list[FKCandidate]:
        """Run full FK inference pipeline (Stage 1 + Stage 2) and persist.

        Returns:
            List of validated FKCandidate objects, sorted by confidence.
        """
        t0 = time.perf_counter()

        candidates = self.stage1_name_matching(schema_name)
        candidates = self.stage2_validate(schema_name, candidates)
        self._persist(schema_name, candidates)

        elapsed = time.perf_counter() - t0
        logger.info(
            "FK inference complete: %d candidates in %.2fs",
            len(candidates), elapsed,
        )
        return candidates

    def evaluate(
        self,
        schema_name: str,
        ground_truth: Optional[list[tuple[str, str, str, str]]] = None,
        confidence_threshold: float = 0.5,
    ) -> dict:
        """Evaluate FK inference against known ground truth.

        Runs full pipeline, then computes precision, recall, F1 against
        the provided ground truth relationships.

        Args:
            schema_name: Schema to analyze.
            ground_truth: List of (src_table, src_col, tgt_table, tgt_col) tuples.
                          Defaults to SYNTHETIC_DB_GROUND_TRUTH.
            confidence_threshold: Minimum confidence to count as a prediction.

        Returns:
            Dict with precision, recall, F1, true_positives, false_positives,
            false_negatives, and detailed breakdown.
        """
        if ground_truth is None:
            ground_truth = SYNTHETIC_DB_GROUND_TRUTH

        gt_set = {(s, sc, t, tc) for s, sc, t, tc in ground_truth}

        candidates = self.stage1_name_matching(schema_name)
        candidates = self.stage2_validate(schema_name, candidates)

        # Filter by confidence threshold
        predictions = {
            (c.src_table, c.src_column, c.tgt_table, c.tgt_column)
            for c in candidates
            if c.confidence >= confidence_threshold
        }

        tp = predictions & gt_set
        fp = predictions - gt_set
        fn = gt_set - predictions

        precision = len(tp) / len(predictions) if predictions else 0.0
        recall = len(tp) / len(gt_set) if gt_set else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0 else 0.0
        )

        report = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "true_positives": len(tp),
            "false_positives": len(fp),
            "false_negatives": len(fn),
            "total_ground_truth": len(gt_set),
            "total_predictions": len(predictions),
            "confidence_threshold": confidence_threshold,
            "tp_details": sorted(tp),
            "fp_details": sorted(fp),
            "fn_details": sorted(fn),
        }

        # Print readable summary
        lines = [
            "",
            "=" * 60,
            "FK Inference Evaluation Report",
            "=" * 60,
            f"Ground truth:  {len(gt_set)} relationships",
            f"Predicted:     {len(predictions)} (confidence >= {confidence_threshold})",
            f"",
            f"Precision:     {precision:.1%}  ({len(tp)} correct / {len(predictions)} predicted)",
            f"Recall:        {recall:.1%}  ({len(tp)} found / {len(gt_set)} actual)",
            f"F1 Score:      {f1:.3f}",
            "",
        ]

        if fp:
            lines.append(f"FALSE POSITIVES ({len(fp)}):")
            for s, sc, t, tc in sorted(fp):
                # Find the candidate for details
                cand = next(
                    (c for c in candidates
                     if c.src_table == s and c.src_column == sc
                     and c.tgt_table == t and c.tgt_column == tc),
                    None,
                )
                detail = ""
                if cand and cand.inclusion_pct is not None:
                    detail = f"  (inclusion: {cand.inclusion_pct:.1f}%, conf: {cand.confidence:.2f})"
                lines.append(f"  {s}.{sc} -> {t}.{tc}{detail}")
            lines.append("")

        if fn:
            lines.append(f"FALSE NEGATIVES ({len(fn)}) - missed relationships:")
            for s, sc, t, tc in sorted(fn):
                lines.append(f"  {s}.{sc} -> {t}.{tc}")
            lines.append("")

        report["summary"] = "\n".join(lines)
        logger.info(report["summary"])

        return report

    # ------------------------------------------------------------------
    # Internal: metadata queries
    # ------------------------------------------------------------------

    def _get_primary_keys(
        self, conn, schema_name: str,
    ) -> dict[str, list[tuple[str, str]]]:
        """Get PK columns for all tables in the schema.

        Returns:
            Dict mapping table_name -> list of (column_name, data_type).
        """
        if self._dialect == "mssql":
            rows = conn.execute(text("""
                SELECT
                    t.name AS table_name,
                    c.name AS column_name,
                    tp.name AS data_type
                FROM sys.key_constraints kc
                INNER JOIN sys.tables t ON kc.parent_object_id = t.object_id
                INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
                INNER JOIN sys.index_columns ic
                    ON ic.object_id = kc.parent_object_id
                    AND ic.index_id = kc.unique_index_id
                INNER JOIN sys.columns c
                    ON c.object_id = ic.object_id
                    AND c.column_id = ic.column_id
                INNER JOIN sys.types tp ON c.user_type_id = tp.user_type_id
                WHERE s.name = :schema
                    AND kc.type = 'PK'
                ORDER BY t.name, ic.key_ordinal
            """), {"schema": schema_name}).fetchall()
        else:
            # PostgreSQL
            rows = conn.execute(text("""
                SELECT
                    tc.table_name,
                    kcu.column_name,
                    c.udt_name AS data_type
                FROM information_schema.table_constraints tc
                INNER JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                INNER JOIN information_schema.columns c
                    ON c.table_schema = kcu.table_schema
                    AND c.table_name = kcu.table_name
                    AND c.column_name = kcu.column_name
                WHERE tc.table_schema = :schema
                    AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY tc.table_name, kcu.ordinal_position
            """), {"schema": schema_name}).fetchall()

        pk_map: dict[str, list[tuple[str, str]]] = {}
        for table, col, dtype in rows:
            if table not in pk_map:
                pk_map[table] = []
            pk_map[table].append((col, dtype))

        return pk_map

    def _get_all_columns(
        self, conn, schema_name: str,
    ) -> list[tuple[str, str, str]]:
        """Get all columns with their data types.

        Returns:
            List of (table_name, column_name, data_type) tuples.
        """
        if self._dialect == "mssql":
            rows = conn.execute(text("""
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = :schema
                ORDER BY TABLE_NAME, ORDINAL_POSITION
            """), {"schema": schema_name}).fetchall()
        else:
            rows = conn.execute(text("""
                SELECT table_name, column_name, udt_name
                FROM information_schema.columns
                WHERE table_schema = :schema
                ORDER BY table_name, ordinal_position
            """), {"schema": schema_name}).fetchall()

        return [(r[0], r[1], r[2]) for r in rows]

    # ------------------------------------------------------------------
    # Internal: type compatibility
    # ------------------------------------------------------------------

    @staticmethod
    def _types_compatible(type_a: str, type_b: str) -> bool:
        """Check if two column types are compatible for FK relationship.

        Uses type family grouping rather than exact match, since VARCHAR(20)
        and VARCHAR(10) are compatible, as are INT and BIGINT.
        """
        # Normalize to lowercase
        a, b = type_a.lower(), type_b.lower()

        # Exact match
        if a == b:
            return True

        # Define compatible type families
        string_types = {"varchar", "nvarchar", "char", "nchar", "text", "ntext",
                        "character varying", "character", "bpchar"}
        int_types = {"int", "integer", "bigint", "smallint", "tinyint",
                     "int4", "int8", "int2", "serial", "bigserial"}
        numeric_types = {"numeric", "decimal", "float", "real", "money",
                         "smallmoney", "double precision", "float8", "float4"}
        date_types = {"date", "datetime", "datetime2", "timestamp",
                      "timestamp without time zone", "timestamp with time zone"}

        families = [string_types, int_types, numeric_types, date_types]
        for family in families:
            if a in family and b in family:
                return True

        return False

    # ------------------------------------------------------------------
    # Internal: Stage 2 validation
    # ------------------------------------------------------------------

    def _validate_candidate(
        self,
        conn,
        schema_name: str,
        cand: FKCandidate,
    ) -> None:
        """Run inclusion dependency check for a single candidate.

        Updates the candidate's validation fields and confidence in-place.
        """
        sq = self._q(schema_name)
        st = self._q(cand.src_table)
        sc = self._q(cand.src_column)
        tt = self._q(cand.tgt_table)
        tc = self._q(cand.tgt_column)

        # --- 1. Count FK values not found in PK (violations) ---
        violation_query = f"""
            SELECT COUNT(*) FROM (
                SELECT DISTINCT {sq}.{st}.{sc} AS fk_val
                FROM {sq}.{st}
                WHERE {sq}.{st}.{sc} IS NOT NULL
            ) src
            WHERE src.fk_val NOT IN (
                SELECT {sq}.{tt}.{tc}
                FROM {sq}.{tt}
                WHERE {sq}.{tt}.{tc} IS NOT NULL
            )
        """
        cand.violation_count = conn.execute(text(violation_query)).scalar() or 0

        # --- 2. FK distinct count ---
        fk_distinct_query = f"""
            SELECT COUNT(DISTINCT {sc}) FROM {sq}.{st} WHERE {sc} IS NOT NULL
        """
        fk_distinct = conn.execute(text(fk_distinct_query)).scalar() or 0

        # --- 3. PK distinct count ---
        pk_distinct_query = f"""
            SELECT COUNT(DISTINCT {tc}) FROM {sq}.{tt} WHERE {tc} IS NOT NULL
        """
        pk_distinct = conn.execute(text(pk_distinct_query)).scalar() or 0

        # --- 4. FK total and null count ---
        fk_total_query = f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN {sc} IS NULL THEN 1 ELSE 0 END) AS nulls
            FROM {sq}.{st}
        """
        fk_row = conn.execute(text(fk_total_query)).fetchone()
        fk_total = fk_row[0] if fk_row else 0
        fk_nulls = fk_row[1] if fk_row else 0

        # --- 5. Compute metrics ---
        cand.fk_null_pct = round(fk_nulls / fk_total * 100, 2) if fk_total > 0 else 0.0

        if fk_distinct > 0:
            cand.inclusion_pct = round(
                (fk_distinct - cand.violation_count) / fk_distinct * 100, 2
            )
        else:
            cand.inclusion_pct = 100.0  # no data = vacuously true

        if pk_distinct > 0:
            cand.cardinality_ratio = round(fk_distinct / pk_distinct, 4)
        else:
            cand.cardinality_ratio = 0.0

        # --- 6. Update confidence based on validation results ---
        if cand.inclusion_pct == 100.0 and fk_distinct > 0:
            cand.confidence = self.CONF_VALIDATED
            cand.validated = True
            cand.inference_method = "inclusion_dep"
        elif cand.inclusion_pct >= 95.0:
            cand.confidence = self.CONF_PARTIAL
            cand.validated = True
            cand.inference_method = "inclusion_dep"
        elif cand.inclusion_pct >= 80.0:
            # Possible FK with data quality issues
            cand.confidence = max(cand.confidence, 0.50)
            cand.validated = False
            cand.inference_method = "name_match"
        else:
            # Likely false positive
            cand.confidence = self.CONF_WEAK
            cand.validated = False
            cand.inference_method = "name_match"

        logger.debug(
            "  %s.%s -> %s.%s: inclusion=%.1f%%, violations=%d, "
            "cardinality=%.2f, null=%.1f%%, conf=%.2f",
            cand.src_table, cand.src_column,
            cand.tgt_table, cand.tgt_column,
            cand.inclusion_pct, cand.violation_count,
            cand.cardinality_ratio, cand.fk_null_pct, cand.confidence,
        )

    # ------------------------------------------------------------------
    # Persistence (writes to PostgreSQL)
    # ------------------------------------------------------------------

    def _persist(self, schema_name: str, candidates: list[FKCandidate]) -> None:
        """UPSERT FK candidates into PostgreSQL public.inferred_fks."""
        if not candidates:
            return

        with self._target.begin() as conn:
            for cand in candidates:
                conn.execute(text("""
                    INSERT INTO public.inferred_fks
                        (src_schema, src_table, src_column,
                         tgt_schema, tgt_table, tgt_column,
                         inference_method, confidence, validated, created_at)
                    VALUES
                        (:schema, :src_t, :src_c,
                         :schema, :tgt_t, :tgt_c,
                         :method, :conf, :val, CURRENT_TIMESTAMP)
                    ON CONFLICT (src_schema, src_table, src_column,
                                 tgt_schema, tgt_table, tgt_column) DO UPDATE SET
                        inference_method = EXCLUDED.inference_method,
                        confidence = EXCLUDED.confidence,
                        validated = EXCLUDED.validated,
                        created_at = CURRENT_TIMESTAMP
                """), {
                    "schema": schema_name,
                    "src_t": cand.src_table,
                    "src_c": cand.src_column,
                    "tgt_t": cand.tgt_table,
                    "tgt_c": cand.tgt_column,
                    "method": cand.inference_method,
                    "conf": cand.confidence,
                    "val": cand.validated,
                })

        logger.info("Persisted %d FK candidates to inferred_fks", len(candidates))

    # ------------------------------------------------------------------
    # Utility: Vanna documentation output
    # ------------------------------------------------------------------

    def format_for_vanna(
        self,
        schema_name: str,
        candidates: Optional[list[FKCandidate]] = None,
        confidence_threshold: float = 0.5,
    ) -> list[str]:
        """Generate Vanna.ai documentation strings describing FK relationships.

        Returns one string per source table, listing its outgoing FK relationships
        as join hints for the LLM.
        """
        if candidates is None:
            candidates = self.run(schema_name)

        # Filter and group by source table
        by_table: dict[str, list[FKCandidate]] = {}
        for c in candidates:
            if c.confidence < confidence_threshold:
                continue
            if c.src_table not in by_table:
                by_table[c.src_table] = []
            by_table[c.src_table].append(c)

        docs = []
        for table in sorted(by_table.keys()):
            fks = by_table[table]
            lines = [f"Relationships for {schema_name}.{table}:"]
            for fk in fks:
                validated_str = " (validated)" if fk.validated else ""
                lines.append(
                    f"  - {table}.{fk.src_column} references "
                    f"{fk.tgt_table}.{fk.tgt_column}{validated_str}"
                )
            docs.append("\n".join(lines))

        return docs

    # ------------------------------------------------------------------
    # Utility: summary for inspection
    # ------------------------------------------------------------------

    def summary(
        self,
        candidates: list[FKCandidate],
        confidence_threshold: float = 0.0,
    ) -> str:
        """Human-readable summary of inference results."""
        filtered = [c for c in candidates if c.confidence >= confidence_threshold]

        lines = [
            f"FK Inference Summary",
            f"{'=' * 60}",
            f"Total candidates: {len(candidates)}",
            f"Above threshold ({confidence_threshold}): {len(filtered)}",
            f"Validated (Stage 2): {sum(1 for c in filtered if c.validated)}",
            "",
        ]

        for c in filtered:
            val_mark = "V" if c.validated else " "
            incl_str = f"{c.inclusion_pct:.0f}%" if c.inclusion_pct is not None else "n/a"
            lines.append(
                f"  [{val_mark}] {c.src_table}.{c.src_column} -> "
                f"{c.tgt_table}.{c.tgt_column}  "
                f"({c.match_type}, conf={c.confidence:.2f}, incl={incl_str})"
            )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Defaults: synthetic DB in PostgreSQL (same host for source + target)
    try:
        from config import MSSQL_URL, DATABASE_URL, BANK_SCHEMA
        DEFAULT_SOURCE = MSSQL_URL
        DEFAULT_TARGET = DATABASE_URL
        DEFAULT_DIALECT = "mssql"
    except ImportError:
        DEFAULT_SOURCE = (
            "postgresql://dbnavigator:dbnavigator_dev@localhost:5432/dbnavigator"
        )
        DEFAULT_TARGET = DEFAULT_SOURCE
        DEFAULT_DIALECT = "postgresql"

    source_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE
    target_url = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_TARGET
    schema = sys.argv[3] if len(sys.argv) > 3 else "bank"
    dialect = sys.argv[4] if len(sys.argv) > 4 else DEFAULT_DIALECT

    fk = FKInference(
        source_url=source_url,
        target_url=target_url,
        dialect=dialect,
    )

    if "--evaluate" in sys.argv:
        report = fk.evaluate(schema, ground_truth=SYNTHETIC_DB_GROUND_TRUTH)
        print(report["summary"])
    elif "--stage1" in sys.argv:
        candidates = fk.stage1_name_matching(schema)
        print(fk.summary(candidates))
    elif "--vanna" in sys.argv:
        docs = fk.format_for_vanna(schema)
        for doc in docs:
            print(doc)
            print()
    else:
        candidates = fk.run(schema)
        print(fk.summary(candidates))
"""Evaluation Runner for DB-Navigator AI.

Runs benchmark queries against the system, compares generated SQL results
with gold-standard SQL results, and produces accuracy metrics.

Supports ablation configurations to isolate each enrichment component's
contribution (RQ3) and multi-model comparison (RQ4).

Architecture:
    - Reads benchmark questions from PostgreSQL public.benchmark table
    - Generates SQL via Vanna.ai with configurable training data
    - Executes both generated and gold SQL on the source database
    - Compares result sets for execution accuracy
    - Logs all results to PostgreSQL public.query_log
    - Outputs summary statistics by difficulty, category, and overall

Ablation configurations:
    A: DDL only (baseline)
    B: DDL + sample values
    C: DDL + LLM descriptions
    D: DDL + FK relationship docs
    E: Full enrichment (DDL + values + descriptions + FKs)
    F: Full enrichment + SQL examples

Usage:
    python -m app.evaluation.benchmark --config E
    python -m app.evaluation.benchmark --config A --model gpt-4o-mini
    python -m app.evaluation.benchmark --list
    python -m app.evaluation.benchmark --config E --difficulty easy
"""

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    question_id: int
    question: str
    difficulty: str
    category: str
    gold_sql: str
    generated_sql: Optional[str] = None
    gold_result: Optional[pd.DataFrame] = None
    generated_result: Optional[pd.DataFrame] = None
    is_correct: bool = False
    error_type: Optional[str] = None
    error_detail: Optional[str] = None
    latency_ms: int = 0
    correction_iters: int = 0
    vote_confidence: Optional[float] = None


@dataclass
class BenchmarkSummary:
    config: str
    model: str
    total: int = 0
    correct: int = 0
    incorrect: int = 0
    errors: int = 0
    accuracy: float = 0.0
    by_difficulty: dict = field(default_factory=dict)
    by_category: dict = field(default_factory=dict)
    error_types: dict = field(default_factory=dict)
    elapsed_sec: float = 0.0
    correction_enabled: bool = False
    correction_iters_total: int = 0
    corrected_count: int = 0
    voting_enabled: bool = False
    voting_n: int = 0
    mean_confidence: Optional[float] = None
    join_paths_enabled: bool = False
    value_check_enabled: bool = False
    code_glossary_enabled: bool = False


# ---------------------------------------------------------------------------
# Ablation configurations
# ---------------------------------------------------------------------------

ABLATION_CONFIGS = {
    "A": {
        "name": "DDL only (baseline)",
        "ddl": True,
        "sample_values": False,
        "descriptions": False,
        "fk_docs": False,
        "domain_docs": False,
        "sql_examples": False,
    },
    "B": {
        "name": "DDL + sample values",
        "ddl": True,
        "sample_values": True,
        "descriptions": False,
        "fk_docs": False,
        "domain_docs": False,
        "sql_examples": False,
    },
    "C": {
        "name": "DDL + LLM descriptions",
        "ddl": True,
        "sample_values": False,
        "descriptions": True,
        "fk_docs": False,
        "domain_docs": False,
        "sql_examples": False,
    },
    "D": {
        "name": "DDL + FK docs",
        "ddl": True,
        "sample_values": False,
        "descriptions": False,
        "fk_docs": True,
        "domain_docs": False,
        "sql_examples": False,
    },
    "E": {
        "name": "Full enrichment",
        "ddl": True,
        "sample_values": True,
        "descriptions": True,
        "fk_docs": True,
        "domain_docs": True,
        "sql_examples": False,
    },
    "F": {
        "name": "Full enrichment + SQL examples",
        "ddl": True,
        "sample_values": True,
        "descriptions": True,
        "fk_docs": True,
        "domain_docs": True,
        "sql_examples": True,
    },
}


# ---------------------------------------------------------------------------
# Vanna setup per ablation config
# ---------------------------------------------------------------------------

def _create_vanna(api_key: str, model: str = "gpt-4o-mini"):
    from vanna.openai import OpenAI_Chat
    from vanna.chromadb import ChromaDB_VectorStore

    class VN(ChromaDB_VectorStore, OpenAI_Chat):
        def __init__(self):
            ChromaDB_VectorStore.__init__(
                self, config={"persist_directory": "/tmp/vanna_eval"}
            )
            OpenAI_Chat.__init__(
                self, config={"api_key": api_key, "model": model}
            )

    return VN()


def _clear_vanna(vn):
    td = vn.get_training_data()
    if td is not None and len(td) > 0:
        for _, row in td.iterrows():
            vn.remove_training_data(row["id"])


def _train_vanna(
    vn,
    source_engine: Engine,
    target_engine: Engine,
    schema: str,
    config: dict,
    api_key: str,
):
    _clear_vanna(vn)

    # DDL (always included)
    if config["ddl"]:
        with source_engine.connect() as conn:
            tables = conn.execute(text("""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = :schema AND TABLE_TYPE = 'BASE TABLE'
                ORDER BY TABLE_NAME
            """), {"schema": schema}).fetchall()

            for (table_name,) in tables:
                cols = conn.execute(text("""
                    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE,
                           CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table
                    ORDER BY ORDINAL_POSITION
                """), {"schema": schema, "table": table_name}).fetchall()

                ddl_lines = [f"CREATE TABLE [{schema}].[{table_name}] ("]
                for col_name, dtype, nullable, max_len, num_prec in cols:
                    type_str = dtype.upper()
                    if max_len:
                        type_str += f"({max_len})"
                    elif num_prec:
                        type_str += f"({num_prec})"
                    null_str = "" if nullable == "YES" else " NOT NULL"
                    ddl_lines.append(f"    [{col_name}] {type_str}{null_str},")
                ddl_lines[-1] = ddl_lines[-1].rstrip(",")
                ddl_lines.append(");")
                vn.train(ddl="\n".join(ddl_lines))

    # Sample values (from metadata extractor)
    if config["sample_values"]:
        from app.enrichment.metadata_extractor import MetadataExtractor
        ext = MetadataExtractor(
            source_url="",
            target_url="",
            source_engine=source_engine,
            target_engine=target_engine,
        )
        for doc in ext.format_for_vanna(schema):
            vn.train(documentation=doc)

    # LLM descriptions
    if config["descriptions"]:
        from app.enrichment.description_gen import DescriptionGenerator
        gen = DescriptionGenerator(
            source_url="",
            target_url="",
            api_key=api_key,
            dialect="mssql",
            source_engine=source_engine,
            target_engine=target_engine,
        )
        for doc in gen.format_for_vanna(schema):
            vn.train(documentation=doc)

    # FK relationship docs
    if config["fk_docs"]:
        from app.enrichment.fk_inference import FKInference
        fk = FKInference(
            source_url="",
            target_url="",
            dialect="mssql",
            source_engine=source_engine,
            target_engine=target_engine,
        )
        for doc in fk.format_for_vanna(schema):
            vn.train(documentation=doc)

    # Domain docs
    if config["domain_docs"]:
        domain_docs = [
            "The bank schema contains tables for Moldova Agroindbank (MAIB), Moldova's largest bank.",
            "cust_tp 'PF' means Persoana Fizica (individual), 'PJ' means Persoana Juridica (company).",
            "ccy_cd is currency code: MDL = Moldovan Leu, USD = US Dollar, EUR = Euro, RON = Romanian Leu.",
            "dr_cr_ind: 'D' = debit (money out), 'C' = credit (money in).",
            "npl_flag: 'Y' = non-performing loan (overdue > 90 days), 'N' = performing.",
            "IDNP = Numarul de Identificare de Stat al Persoanei (Moldova national ID).",
            "Account status values in tbl_acct.stat_cd: 'OPEN' = active account, 'FROZEN' = frozen account, 'CLOSED' = closed account, 'DORMANT' = dormant/inactive account.",
            "Customer status values in tbl_cust.stat_cd: 'ACTIVE' = active customer, 'DORMANT' = dormant customer, 'BLOCKED' = blocked customer.",
            "Branch status in tbl_br.stat_cd: 1 = active branch, 0 = closed branch (integer, not string).",
            "tbl_txn contains all financial transactions. Use acct_no to join to tbl_acct, and txn_tp_cd to join to tbl_txn_tp.",
            "tbl_loan tracks all loans. disb_acct_no and repay_acct_no link to accounts in tbl_acct.",
        ]
        for doc in domain_docs:
            vn.train(documentation=doc)

    # SQL examples
    if config["sql_examples"]:
        examples = [
            ("Show me all active customers",
             f"SELECT * FROM [{schema}].[tbl_cust] WHERE [stat_cd] = 'ACTIVE'"),
            ("How many accounts does each customer have?",
             f"SELECT [cust_no], COUNT(*) as account_count FROM [{schema}].[tbl_acct] GROUP BY [cust_no] ORDER BY account_count DESC"),
            ("What is the total loan portfolio by product category?",
             f"SELECT lp.[prod_categ], COUNT(l.[loan_no]) as loan_count, SUM(l.[outst_princ]) as total_outstanding FROM [{schema}].[tbl_loan] l JOIN [{schema}].[tbl_loan_prod] lp ON l.[prod_cd] = lp.[prod_cd] WHERE l.[stat_cd] = 'ACTIVE' GROUP BY lp.[prod_categ] ORDER BY total_outstanding DESC"),
            ("Show me all non-performing loans with customer details",
             f"SELECT c.[cust_nm], l.[loan_no], l.[loan_amt], l.[outst_princ], l.[overdue_amt], l.[overdue_days] FROM [{schema}].[tbl_loan] l JOIN [{schema}].[tbl_cust] c ON l.[cust_no] = c.[cust_no] WHERE l.[npl_flag] = 'Y'"),
            ("What are the top 5 accounts by current balance?",
             f"SELECT TOP 5 a.[acct_no], c.[cust_nm], a.[ccy_cd], a.[cur_bal] FROM [{schema}].[tbl_acct] a JOIN [{schema}].[tbl_cust] c ON a.[cust_no] = c.[cust_no] WHERE a.[stat_cd] = 'OPEN' ORDER BY a.[cur_bal] DESC"),
            ("Show transactions for account ACC-001 in February 2025",
             f"SELECT t.[txn_dt], t.[txn_amt], t.[dr_cr_ind], t.[descr], tp.[txn_tp_nm] FROM [{schema}].[tbl_txn] t JOIN [{schema}].[tbl_txn_tp] tp ON t.[txn_tp_cd] = tp.[txn_tp_cd] WHERE t.[acct_no] = 'MD24AG000000000001MDL' AND t.[txn_dt] >= '2025-02-01' AND t.[txn_dt] < '2025-03-01' ORDER BY t.[txn_dt]"),
            ("Which branches have more than 3 employees?",
             f"SELECT b.[br_nm], COUNT(e.[emp_no]) as emp_count FROM [{schema}].[tbl_br] b JOIN [{schema}].[tbl_emp] e ON b.[br_cd] = e.[br_cd] WHERE e.[stat_cd] = 1 GROUP BY b.[br_nm] HAVING COUNT(e.[emp_no]) > 3"),
            ("Show me customers with both loans and cards",
             f"SELECT DISTINCT c.[cust_no], c.[cust_nm] FROM [{schema}].[tbl_cust] c WHERE c.[cust_no] IN (SELECT [cust_no] FROM [{schema}].[tbl_loan]) AND c.[cust_no] IN (SELECT [cust_no] FROM [{schema}].[tbl_card])"),
        ]
        for question, sql in examples:
            vn.train(question=question, sql=sql)

    td = vn.get_training_data()
    counts = td["training_data_type"].value_counts().to_dict() if td is not None else {}
    logger.info("Vanna trained: %s", counts)
    return counts


# ---------------------------------------------------------------------------
# Result comparison
# ---------------------------------------------------------------------------

def _fix_tsql(sql: str) -> str:
    if sql is None:
        return sql
    import re
    sql = sql.strip().rstrip(";").strip()
    match = re.search(r'\bLIMIT\s+(\d+)\s*$', sql, re.IGNORECASE)
    if match:
        n = match.group(1)
        sql = re.sub(r'\bLIMIT\s+\d+\s*$', '', sql, flags=re.IGNORECASE).strip()
        sql = re.sub(r'^SELECT\b', f'SELECT TOP {n}', sql, count=1, flags=re.IGNORECASE)
    return sql


def _execute_sql(engine: Engine, sql: str, timeout: int = 30) -> tuple:
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
            return df, None
    except Exception as e:
        return None, str(e)


def _compare_results(gold_df: pd.DataFrame, gen_df: pd.DataFrame) -> bool:
    if gold_df is None or gen_df is None:
        return False

    if gold_df.empty and gen_df.empty:
        return True

    if len(gold_df) != len(gen_df):
        return False

    # Strategy 1: Find common columns by name and compare those
    gold_cols_lower = {c.lower(): c for c in gold_df.columns}
    gen_cols_lower = {c.lower(): c for c in gen_df.columns}
    common_keys = set(gold_cols_lower.keys()) & set(gen_cols_lower.keys())

    if common_keys:
        gold_subset = gold_df[[gold_cols_lower[k] for k in common_keys]].copy()
        gen_subset = gen_df[[gen_cols_lower[k] for k in common_keys]].copy()
        gold_subset.columns = sorted(common_keys)
        gen_subset.columns = sorted(common_keys)
        try:
            gold_tuples = set()
            gen_tuples = set()
            for _, row in gold_subset.iterrows():
                gold_tuples.add(tuple(str(v).strip() for v in row))
            for _, row in gen_subset.iterrows():
                gen_tuples.add(tuple(str(v).strip() for v in row))
            if gold_tuples == gen_tuples:
                return True
        except Exception:
            pass

    # Strategy 2: Compare by values only (ignore column names)
    if len(gold_df.columns) == len(gen_df.columns):
        try:
            gold_tuples = set()
            gen_tuples = set()
            for _, row in gold_df.iterrows():
                gold_tuples.add(tuple(str(v).strip() for v in row))
            for _, row in gen_df.iterrows():
                gen_tuples.add(tuple(str(v).strip() for v in row))
            if gold_tuples == gen_tuples:
                return True
        except Exception:
            pass

    # Strategy 3: If generated has more columns, check common subset
    if len(gen_df.columns) > len(gold_df.columns) and common_keys:
        gold_subset = gold_df[[gold_cols_lower[k] for k in common_keys]].copy()
        gen_subset = gen_df[[gen_cols_lower[k] for k in common_keys]].copy()
        gold_subset.columns = sorted(common_keys)
        gen_subset.columns = sorted(common_keys)
        try:
            gold_tuples = set()
            gen_tuples = set()
            for _, row in gold_subset.iterrows():
                gold_tuples.add(tuple(str(v).strip() for v in row))
            for _, row in gen_subset.iterrows():
                gen_tuples.add(tuple(str(v).strip() for v in row))
            if gold_tuples == gen_tuples:
                return True
        except Exception:
            pass

    return False


def _classify_error(
    gold_sql: str,
    generated_sql: str,
    gold_result: Optional[pd.DataFrame],
    gen_result: Optional[pd.DataFrame],
    gen_error: Optional[str],
) -> tuple:
    if generated_sql is None:
        return "generation_failed", "LLM returned no SQL"

    if gen_error:
        err_lower = gen_error.lower()
        if "syntax" in err_lower:
            return "syntax_error", gen_error[:200]
        if "invalid column" in err_lower or "invalid object" in err_lower:
            return "schema_linking", gen_error[:200]
        return "execution_error", gen_error[:200]

    if gen_result is None:
        return "execution_error", "No result returned"

    if gold_result is None:
        return "gold_error", "Gold SQL failed to execute"

    # Both executed but results differ
    gold_lower = gold_sql.lower()
    gen_lower = generated_sql.lower()

    if "join" in gold_lower and "join" not in gen_lower:
        return "missing_join", "Gold uses JOIN but generated does not"
    if gen_lower.count("join") != gold_lower.count("join"):
        return "wrong_join", "Different number of JOINs"

    if "group by" in gold_lower and "group by" not in gen_lower:
        return "missing_aggregation", "Gold uses GROUP BY but generated does not"

    if "where" in gold_lower and "where" not in gen_lower:
        return "missing_filter", "Gold has WHERE clause but generated does not"

    # Check for value mapping errors (wrong string literals)
    import re
    gold_strings = set(re.findall(r"'([^']+)'", gold_sql))
    gen_strings = set(re.findall(r"'([^']+)'", generated_sql))
    if gold_strings != gen_strings:
        return "value_mapping", f"Gold values: {gold_strings}, Generated: {gen_strings}"

    if len(gold_result) != len(gen_result):
        return "wrong_result_count", f"Gold: {len(gold_result)} rows, Generated: {len(gen_result)} rows"

    return "result_mismatch", "Results differ but no specific pattern identified"


# ---------------------------------------------------------------------------
# Main benchmark runner
# ---------------------------------------------------------------------------

class BenchmarkRunner:

    QUERY_TIMEOUT = 30

    def __init__(
        self,
        source_url: str,
        target_url: str,
        api_key: str,
        schema: str = "bank",
        model: str = "gpt-4o-mini",
        self_correct: bool = False,
        correct_iters: int = 2,
        correct_retry_empty: bool = False,
        correct_temperature: float = 0.0,
        voting: bool = False,
        voting_n: int = 5,
        voting_temperature: float = 0.7,
        join_paths: bool = False,
        value_check: bool = False,
        code_glossary: bool = False,
    ):
        self._source = create_engine(source_url)
        self._target = create_engine(target_url)
        self._api_key = api_key
        self._schema = schema
        self._model = model
        self._self_correct = self_correct
        self._correct_iters = correct_iters
        self._correct_retry_empty = correct_retry_empty
        self._correct_temperature = correct_temperature
        self._voting = voting
        self._voting_n = voting_n
        self._voting_temperature = voting_temperature
        self._join_paths = join_paths
        self._join_validator = self._build_join_validator() if join_paths else None
        self._value_check = value_check
        self._value_validator = self._build_value_index() if value_check else None
        self._code_glossary = code_glossary
        self._glossary_text = self._build_code_glossary() if code_glossary else None

    def list_benchmarks(self) -> pd.DataFrame:
        with self._target.connect() as conn:
            df = pd.read_sql(text("""
                SELECT id, difficulty, category, question,
                       LEFT(gold_sql, 80) as gold_sql_preview
                FROM public.benchmark
                ORDER BY difficulty, id
            """), conn)
        return df

    def run(
        self,
        config_key: str = "E",
        difficulty: Optional[str] = None,
        limit: Optional[int] = None,
        run_label: Optional[str] = None,
    ) -> BenchmarkSummary:
        config = ABLATION_CONFIGS[config_key]
        logger.info("Running config %s: %s (model: %s)", config_key, config["name"], self._model)

        # Load benchmark questions
        questions = self._load_questions(difficulty, limit)
        if not questions:
            logger.error("No benchmark questions found")
            return BenchmarkSummary(config=config_key, model=self._model)

        logger.info("Loaded %d benchmark questions", len(questions))

        # Setup Vanna with ablation config
        vn = _create_vanna(self._api_key, self._model)
        training_counts = _train_vanna(
            vn, self._source, self._target,
            self._schema, config, self._api_key,
        )
        logger.info("Training complete: %s", training_counts)

        # Run each question
        t0 = time.perf_counter()
        results = []

        for i, q in enumerate(questions):
            logger.info(
                "  [%d/%d] %s: %s",
                i + 1, len(questions), q["difficulty"], q["question"][:60],
            )
            result = self._evaluate_one(vn, q)
            results.append(result)
            self._log_result(result, config_key, run_label)

        elapsed = time.perf_counter() - t0

        # Build summary
        summary = self._build_summary(results, config_key, elapsed)

        # Cleanup
        _clear_vanna(vn)

        return summary

    def _load_questions(
        self,
        difficulty: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        query = "SELECT id, question, gold_sql, difficulty, category FROM public.benchmark"
        params = {}

        if difficulty:
            query += " WHERE difficulty = :diff"
            params["diff"] = difficulty

        query += " ORDER BY id"

        if limit:
            query += f" LIMIT {limit}"

        with self._target.connect() as conn:
            rows = conn.execute(text(query), params).fetchall()

        return [
            {
                "id": r[0],
                "question": r[1],
                "gold_sql": r[2],
                "difficulty": r[3],
                "category": r[4],
            }
            for r in rows
        ]

    def _run_correction(self, vn, question_text: str):
        """Run the execution-guided self-correction loop for one question.

        The loop reuses the benchmark's own executor and T-SQL post-processing,
        so a corrected query is judged by exactly the same comparison path as a
        baseline query. Imported lazily so the default benchmark has no new
        import-time dependency.
        """
        from app.pipeline.self_correction import SelfCorrectionLoop

        loop = SelfCorrectionLoop(
            vn=vn,
            execute_fn=lambda sql: _execute_sql(self._source, sql),
            postprocess_fn=_fix_tsql,
            dialect="mssql",
            max_iters=self._correct_iters,
            retry_on_empty=self._correct_retry_empty,
            repair_temperature=self._correct_temperature,
            logger=logger,
        )
        return loop.run(question_text)

    def _run_voting(self, vn, question_text: str):
        """Run self-consistency voting for one question.

        Reuses the benchmark's executor and T-SQL post-processing so the voted
        query is judged by the same comparison path as a baseline query.
        """
        from app.pipeline.voting import SelfConsistencyVoter

        voter = SelfConsistencyVoter(
            vn=vn,
            execute_fn=lambda sql: _execute_sql(self._source, sql),
            postprocess_fn=_fix_tsql,
            n=self._voting_n,
            temperature=self._voting_temperature,
            logger=logger,
        )
        return voter.run(question_text)

    def _build_join_validator(self):
        """Build a join validator from the validated FK ground-truth graph.

        The runtime validation uses the known-good FK set so the technique is
        measured in isolation from FK-inference errors. Imported lazily.
        """
        from app.enrichment.fk_inference import SYNTHETIC_DB_GROUND_TRUTH
        from app.pipeline.join_paths import JoinPathEngine
        from app.pipeline.join_validator import JoinValidator

        return JoinValidator(JoinPathEngine(SYNTHETIC_DB_GROUND_TRUTH), dialect="tsql")

    def _run_join_paths(self, vn, question_text: str):
        """Generate, validate joins, and re-prompt with the FK path on a miss.

        Returns ``(sql, repaired)``. A single join-repair re-prompt at most.
        """
        raw = vn.generate_sql(question=question_text)
        sql = _fix_tsql(raw) if raw and raw.strip() else None
        repaired = False
        if sql and self._join_validator is not None:
            check = self._join_validator.validate(sql)
            if not check.ok and check.hint:
                raw2 = vn.generate_sql(question=f"{question_text}\n\n{check.hint}")
                if raw2 and raw2.strip():
                    sql = _fix_tsql(raw2)
                repaired = True
        return sql, repaired

    def _build_value_index(self):
        """Build a value-domain validator from column cardinalities + source data.

        Reads the distinct-count metadata in public.enriched_columns to pick the
        low-cardinality coded columns, pulls their actual distinct values from the
        source DB, and attaches the hand-authored opaque-code labels. Measured in
        isolation: the index is built from the database itself, not from any LLM
        output. Imported lazily.
        """
        from app.pipeline.value_index import (
            build_value_index, make_source_fetch, SYNTHETIC_DB_VALUE_LABELS,
        )
        from app.pipeline.value_validator import ValueValidator

        with self._target.connect() as conn:
            rows = conn.execute(text("""
                SELECT table_name, column_name, distinct_count
                FROM public.enriched_columns
                WHERE schema_name = :schema AND distinct_count IS NOT NULL
            """), {"schema": self._schema}).fetchall()
        columns = [(r[0], r[1], r[2]) for r in rows]

        index = build_value_index(
            columns,
            make_source_fetch(self._source, self._schema),
            label_map=SYNTHETIC_DB_VALUE_LABELS,
        )
        logger.info("value-domain index built over %d columns", len(index))
        return ValueValidator(index, dialect="tsql")

    def _run_value_check(self, vn, question_text: str):
        """Generate, validate literal values, and re-prompt with the real domain.

        Returns ``(sql, repaired)``. A single value-repair re-prompt at most.
        """
        raw = vn.generate_sql(question=question_text)
        sql = _fix_tsql(raw) if raw and raw.strip() else None
        repaired = False
        if sql and self._value_validator is not None:
            check = self._value_validator.validate(sql)
            if not check.ok and check.hint:
                raw2 = vn.generate_sql(question=f"{question_text}\n\n{check.hint}")
                if raw2 and raw2.strip():
                    sql = _fix_tsql(raw2)
                repaired = True
        return sql, repaired

    def _build_code_glossary(self):
        """Build the code dictionary that is injected before generation.

        Lookup-backed columns (account/transaction type, loan product) get
        authoritative names from their lookup tables; bare codes use the
        hand-authored data dictionary. Restricted to columns that actually
        exist in enriched_columns. Imported lazily.
        """
        from app.pipeline.code_glossary import build_code_glossary, make_lookup_fetch

        with self._target.connect() as conn:
            rows = conn.execute(text("""
                SELECT table_name, column_name FROM public.enriched_columns
                WHERE schema_name = :schema
            """), {"schema": self._schema}).fetchall()
        present = {(r[0].casefold(), r[1].casefold()) for r in rows}

        glossary = build_code_glossary(
            make_lookup_fetch(self._source, self._schema),
            only_columns=present,
        )
        block = glossary.render()
        logger.info("code glossary built over %d columns (%d chars)", len(glossary), len(block))
        return block

    def _run_glossary(self, vn, question_text: str):
        """Prepend the code dictionary to the question, then generate once."""
        augmented = f"{self._glossary_text}\n\n{question_text}"
        raw = vn.generate_sql(question=augmented)
        return _fix_tsql(raw) if raw and raw.strip() else None

    def _evaluate_one(self, vn, question: dict) -> QueryResult:
        qr = QueryResult(
            question_id=question["id"],
            question=question["question"],
            difficulty=question["difficulty"],
            category=question["category"] or "unknown",
            gold_sql=question["gold_sql"],
        )

        # Generate SQL
        t0 = time.perf_counter()
        if self._voting:
            try:
                vr = self._run_voting(vn, question["question"])
                qr.generated_sql = vr.final_sql
                qr.vote_confidence = vr.confidence
            except Exception as e:
                qr.error_type = "generation_failed"
                qr.error_detail = str(e)[:200]
                qr.latency_ms = int((time.perf_counter() - t0) * 1000)
                return qr
            qr.latency_ms = int((time.perf_counter() - t0) * 1000)
        elif self._join_paths:
            try:
                sql, repaired = self._run_join_paths(vn, question["question"])
                qr.generated_sql = sql
                qr.correction_iters = 1 if repaired else 0
            except Exception as e:
                qr.error_type = "generation_failed"
                qr.error_detail = str(e)[:200]
                qr.latency_ms = int((time.perf_counter() - t0) * 1000)
                return qr
            qr.latency_ms = int((time.perf_counter() - t0) * 1000)
        elif self._value_check:
            try:
                sql, repaired = self._run_value_check(vn, question["question"])
                qr.generated_sql = sql
                qr.correction_iters = 1 if repaired else 0
            except Exception as e:
                qr.error_type = "generation_failed"
                qr.error_detail = str(e)[:200]
                qr.latency_ms = int((time.perf_counter() - t0) * 1000)
                return qr
            qr.latency_ms = int((time.perf_counter() - t0) * 1000)
        elif self._code_glossary:
            try:
                qr.generated_sql = self._run_glossary(vn, question["question"])
            except Exception as e:
                qr.error_type = "generation_failed"
                qr.error_detail = str(e)[:200]
                qr.latency_ms = int((time.perf_counter() - t0) * 1000)
                return qr
            qr.latency_ms = int((time.perf_counter() - t0) * 1000)
        elif self._self_correct:
            try:
                cr = self._run_correction(vn, question["question"])
                qr.generated_sql = cr.final_sql
                qr.correction_iters = cr.iterations
            except Exception as e:
                qr.error_type = "generation_failed"
                qr.error_detail = str(e)[:200]
                qr.latency_ms = int((time.perf_counter() - t0) * 1000)
                return qr
            qr.latency_ms = int((time.perf_counter() - t0) * 1000)
        else:
            try:
                sql = vn.generate_sql(question=question["question"])
                if sql and sql.strip():
                    qr.generated_sql = _fix_tsql(sql)
            except Exception as e:
                qr.error_type = "generation_failed"
                qr.error_detail = str(e)[:200]
                qr.latency_ms = int((time.perf_counter() - t0) * 1000)
                return qr

            qr.latency_ms = int((time.perf_counter() - t0) * 1000)

        if not qr.generated_sql:
            qr.error_type = "generation_failed"
            qr.error_detail = "Empty SQL returned"
            return qr

        # Execute gold SQL
        gold_df, gold_err = _execute_sql(self._source, question["gold_sql"])
        if gold_err:
            logger.warning("Gold SQL failed for Q%d: %s", question["id"], gold_err)
            qr.error_type = "gold_error"
            qr.error_detail = gold_err[:200]
            return qr
        qr.gold_result = gold_df

        # Execute generated SQL
        gen_df, gen_err = _execute_sql(self._source, qr.generated_sql)
        qr.generated_result = gen_df

        if gen_err:
            qr.error_type, qr.error_detail = _classify_error(
                qr.gold_sql, qr.generated_sql, gold_df, None, gen_err,
            )
            return qr

        # Compare results
        qr.is_correct = _compare_results(gold_df, gen_df)

        if not qr.is_correct:
            qr.error_type, qr.error_detail = _classify_error(
                qr.gold_sql, qr.generated_sql, gold_df, gen_df, None,
            )

        return qr

    def _log_result(
        self,
        result: QueryResult,
        config_key: str,
        run_label: Optional[str],
    ):
        with self._target.begin() as conn:
            conn.execute(text("""
                INSERT INTO public.query_log
                    (question, generated_sql, executed_ok, execution_error,
                     result_rows, feedback_note, llm_model, latency_ms)
                VALUES
                    (:question, :sql, :ok, :error, :rows, :note, :model, :latency)
            """), {
                "question": result.question,
                "sql": result.generated_sql,
                "ok": result.is_correct,
                "error": result.error_detail,
                "rows": len(result.generated_result) if result.generated_result is not None else None,
                "note": f"config={config_key} label={run_label or 'default'} error_type={result.error_type or 'none'}",
                "model": self._model,
                "latency": result.latency_ms,
            })

        # --- CSV export for McNemar (added) ---
        import csv, os
        _csv_path = "benchmark_results.csv"
        _need_header = not os.path.exists(_csv_path)
        with open(_csv_path, "a", newline="", encoding="utf-8") as _f:
            _w = csv.writer(_f)
            if _need_header:
                _w.writerow(["question_id", "config", "correct"])
            _w.writerow([result.question_id, config_key, 1 if result.is_correct else 0])

    def _build_summary(
        self,
        results: list[QueryResult],
        config_key: str,
        elapsed: float,
    ) -> BenchmarkSummary:
        summary = BenchmarkSummary(
            config=config_key,
            model=self._model,
            total=len(results),
            correct=sum(1 for r in results if r.is_correct),
            incorrect=sum(1 for r in results if not r.is_correct and r.error_type != "gold_error"),
            errors=sum(1 for r in results if r.error_type == "gold_error"),
            elapsed_sec=round(elapsed, 2),
        )
        summary.accuracy = round(summary.correct / max(summary.total, 1) * 100, 1)

        # By difficulty
        for diff in ["easy", "medium", "hard", "extra-hard"]:
            subset = [r for r in results if r.difficulty == diff]
            if subset:
                correct = sum(1 for r in subset if r.is_correct)
                summary.by_difficulty[diff] = {
                    "total": len(subset),
                    "correct": correct,
                    "accuracy": round(correct / len(subset) * 100, 1),
                }

        # By category
        categories = set(r.category for r in results)
        for cat in sorted(categories):
            subset = [r for r in results if r.category == cat]
            correct = sum(1 for r in subset if r.is_correct)
            summary.by_category[cat] = {
                "total": len(subset),
                "correct": correct,
                "accuracy": round(correct / len(subset) * 100, 1),
            }

        # Error types
        for r in results:
            if r.error_type:
                summary.error_types[r.error_type] = summary.error_types.get(r.error_type, 0) + 1

        # Self-correction stats
        summary.correction_enabled = self._self_correct
        summary.correction_iters_total = sum(getattr(r, "correction_iters", 0) for r in results)
        summary.corrected_count = sum(1 for r in results if getattr(r, "correction_iters", 0) > 0)

        # Voting stats
        summary.voting_enabled = self._voting
        summary.voting_n = self._voting_n
        confidences = [r.vote_confidence for r in results if r.vote_confidence is not None]
        summary.mean_confidence = (sum(confidences) / len(confidences)) if confidences else None

        # Join-path stats (re-uses correction_iters to count join repairs)
        summary.join_paths_enabled = self._join_paths
        summary.value_check_enabled = self._value_check
        summary.code_glossary_enabled = self._code_glossary

        return summary


def print_summary(summary: BenchmarkSummary):
    print()
    print("=" * 60)
    print(f"BENCHMARK RESULTS - Config {summary.config}")
    print("=" * 60)
    config = ABLATION_CONFIGS.get(summary.config, {})
    print(f"Configuration: {config.get('name', summary.config)}")
    print(f"Model: {summary.model}")
    print(f"Time: {summary.elapsed_sec}s")
    print()
    print(f"Overall: {summary.correct}/{summary.total} correct ({summary.accuracy}%)")
    print()

    if summary.correction_enabled:
        print("Self-correction:")
        print(f"  queries that triggered a repair: {summary.corrected_count}/{summary.total}")
        print(f"  total repair iterations: {summary.correction_iters_total}")
        print()

    if summary.voting_enabled:
        print("Self-consistency voting:")
        print(f"  candidates per question: {summary.voting_n}")
        if summary.mean_confidence is not None:
            print(f"  mean vote agreement (confidence): {summary.mean_confidence:.2f}")
        print()

    if summary.join_paths_enabled:
        print("Join-path validation:")
        print(f"  queries re-prompted with an FK path: {summary.corrected_count}/{summary.total}")
        print()

    if summary.value_check_enabled:
        print("Value-domain validation:")
        print(f"  queries re-prompted with the real value domain: {summary.corrected_count}/{summary.total}")
        print()

    if summary.code_glossary_enabled:
        print("Code-glossary injection: on (code dictionary prepended to every question)")
        print()

    if summary.by_difficulty:
        print("By difficulty:")
        for diff, stats in summary.by_difficulty.items():
            print(f"  {diff:12s}: {stats['correct']}/{stats['total']} ({stats['accuracy']}%)")
        print()

    if summary.by_category:
        print("By category:")
        for cat, stats in summary.by_category.items():
            print(f"  {cat:20s}: {stats['correct']}/{stats['total']} ({stats['accuracy']}%)")
        print()

    if summary.error_types:
        print("Error breakdown:")
        for etype, count in sorted(summary.error_types.items(), key=lambda x: -x[1]):
            print(f"  {etype:25s}: {count}")
    print()


def print_comparison(summaries: list[BenchmarkSummary]):
    print()
    print("=" * 70)
    print("ABLATION COMPARISON")
    print("=" * 70)
    print(f"{'Config':<8} {'Name':<30} {'Accuracy':>10} {'Correct':>10} {'Total':>8}")
    print("-" * 70)
    for s in summaries:
        name = ABLATION_CONFIGS.get(s.config, {}).get("name", s.config)
        print(f"{s.config:<8} {name:<30} {s.accuracy:>9.1f}% {s.correct:>10} {s.total:>8}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="DB-Navigator AI Benchmark Runner")
    parser.add_argument("source_url", nargs="?", help="SQL Server connection string")
    parser.add_argument("target_url", nargs="?", help="PostgreSQL connection string")
    parser.add_argument("api_key", nargs="?", help="OpenAI API key")
    parser.add_argument("--schema", default="bank", help="Schema name")
    parser.add_argument("--config", default="E", help="Ablation config (A-F) or 'all'")
    parser.add_argument("--model", default="gpt-4o-mini", help="LLM model name")
    parser.add_argument("--difficulty", help="Filter by difficulty level")
    parser.add_argument("--limit", type=int, help="Max questions to run")
    parser.add_argument("--label", help="Run label for logging")
    parser.add_argument("--list", action="store_true", help="List benchmark questions")
    parser.add_argument("--self-correct", action="store_true",
                        help="Enable the execution-guided self-correction loop")
    parser.add_argument("--correct-iters", type=int, default=2,
                        help="Max repair iterations for self-correction (default 2)")
    parser.add_argument("--correct-retry-empty", action="store_true",
                        help="Treat an empty result set as a fault worth repairing")
    parser.add_argument("--correct-temperature", type=float, default=0.0,
                        help="Sampling temperature for repair generations (default 0.0)")
    parser.add_argument("--voting", action="store_true",
                        help="Enable self-consistency voting over multiple candidates")
    parser.add_argument("--voting-n", type=int, default=5,
                        help="Number of candidates to sample per question (default 5)")
    parser.add_argument("--voting-temperature", type=float, default=0.7,
                        help="Sampling temperature for voting candidates (default 0.7)")
    parser.add_argument("--join-paths", action="store_true",
                        help="Enable FK join-path validation and repair")
    parser.add_argument("--value-check", action="store_true",
                        help="Enable value-domain validation and repair")
    parser.add_argument("--code-glossary", action="store_true",
                        help="Inject the code dictionary into the prompt before generation")
    args = parser.parse_args()

    # Try config import (works under `python -m app.evaluation.benchmark`
    # and when run directly from inside the app/ directory)
    try:
        try:
            from app.config import SOURCE_DATABASE_URL, DATABASE_URL, OPENAI_API_KEY
        except ImportError:
            from config import SOURCE_DATABASE_URL, DATABASE_URL, OPENAI_API_KEY
        source = args.source_url or SOURCE_DATABASE_URL
        target = args.target_url or DATABASE_URL
        key = args.api_key or OPENAI_API_KEY
    except ImportError:
        source = args.source_url or ""
        target = args.target_url or ""
        key = args.api_key or ""

    if not source or not target:
        print("Error: source_url and target_url required")
        sys.exit(1)

    runner = BenchmarkRunner(
        source_url=source,
        target_url=target,
        api_key=key,
        schema=args.schema,
        model=args.model,
        self_correct=args.self_correct,
        correct_iters=args.correct_iters,
        correct_retry_empty=args.correct_retry_empty,
        correct_temperature=args.correct_temperature,
        voting=args.voting,
        voting_n=args.voting_n,
        voting_temperature=args.voting_temperature,
        join_paths=args.join_paths,
        value_check=args.value_check,
        code_glossary=args.code_glossary,
    )

    if args.list:
        df = runner.list_benchmarks()
        if df.empty:
            print("No benchmark questions found. Insert questions into public.benchmark table.")
        else:
            print(df.to_string(index=False))
        sys.exit(0)

    if args.config == "all":
        summaries = []
        for config_key in ["A", "B", "C", "D", "E", "F"]:
            s = runner.run(
                config_key=config_key,
                difficulty=args.difficulty,
                limit=args.limit,
                run_label=args.label,
            )
            print_summary(s)
            summaries.append(s)
        print_comparison(summaries)
    else:
        s = runner.run(
            config_key=args.config,
            difficulty=args.difficulty,
            limit=args.limit,
            run_label=args.label,
        )
        print_summary(s)
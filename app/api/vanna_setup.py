"""Vanna setup and Config F training for the API.

Builds the DBNavigator (ChromaDB + OpenAI, gpt-4o-mini) and trains it with the
documented Config F training set: DDL, sample values, LLM descriptions, FK
relationship docs, domain docs, and few-shot SQL examples. The four enrichment
modules are reused as-is; this module only orchestrates training.

Training is idempotent: it runs only when the ChromaDB store for the API is
empty, so a warm container reuses the persisted store and starts fast.

Imports of the enrichment modules and Vanna are deferred into the functions so
this module can be imported in environments where the full stack is not present
(for example, static analysis). Inside the container the working directory is
``/app`` so the enrichment imports use no ``app.`` prefix, matching the
Streamlit app.
"""
import logging
from typing import Optional

from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def build_vanna(persist_directory: str, api_key: str, model: str = "gpt-4o-mini"):
    from vanna.chromadb import ChromaDB_VectorStore
    from vanna.openai import OpenAI_Chat

    class DBNavigator(ChromaDB_VectorStore, OpenAI_Chat):
        def __init__(self):
            ChromaDB_VectorStore.__init__(self, config={"persist_directory": persist_directory})
            OpenAI_Chat.__init__(self, config={"api_key": api_key, "model": model})

    return DBNavigator()


def needs_training(vn) -> bool:
    existing = vn.get_training_data()
    return existing is None or len(existing) == 0


def training_counts(vn) -> dict:
    td = vn.get_training_data()
    if td is None or len(td) == 0:
        return {}
    return td["training_data_type"].value_counts().to_dict()


def train_config_f(
    vn,
    source_engine: Engine,
    target_engine: Engine,
    schema: str,
    api_key: str,
    dialect: str = "mssql",
    include_descriptions: bool = True,
) -> dict:
    """Train Vanna with the Config F set if the store is empty.

    Returns a dict of training-data-type counts.
    """
    if not needs_training(vn):
        counts = training_counts(vn)
        logger.info("Vanna already trained, reusing store: %s", counts)
        return counts

    _train_ddl(vn, source_engine, schema)
    _train_sample_values(vn, source_engine, target_engine, schema)
    if include_descriptions:
        _train_descriptions(vn, source_engine, target_engine, schema, api_key, dialect)
    _train_fk_docs(vn, source_engine, target_engine, schema, dialect)
    _train_domain_docs(vn)
    _train_sql_examples(vn, schema)

    counts = training_counts(vn)
    logger.info("Vanna training complete: %s", counts)
    return counts


def _train_ddl(vn, engine: Engine, schema: str) -> None:
    from sqlalchemy import text

    with engine.connect() as conn:
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
                if max_len and max_len > 0:
                    type_str += f"({max_len})"
                elif num_prec:
                    type_str += f"({num_prec})"
                null_str = "" if nullable == "YES" else " NOT NULL"
                ddl_lines.append(f"    [{col_name}] {type_str}{null_str},")
            ddl_lines[-1] = ddl_lines[-1].rstrip(",")
            ddl_lines.append(");")
            vn.train(ddl="\n".join(ddl_lines))

    logger.info("Trained DDL for %d tables", len(tables))


def _train_sample_values(vn, source_engine: Engine, target_engine: Engine, schema: str) -> None:
    try:
        from enrichment.metadata_extractor import MetadataExtractor
        extractor = MetadataExtractor(
            source_url="",
            target_url="",
            source_engine=source_engine,
            target_engine=target_engine,
        )
        docs = extractor.format_for_vanna(schema)
        for doc in docs:
            vn.train(documentation=doc)
        logger.info("Trained %d sample-value docs", len(docs))
    except Exception as exc:
        logger.warning("Sample-value training failed: %s", exc)


def _train_descriptions(vn, source_engine: Engine, target_engine: Engine, schema: str, api_key: str, dialect: str) -> None:
    try:
        from enrichment.description_gen import DescriptionGenerator
        generator = DescriptionGenerator(
            source_url="",
            target_url="",
            api_key=api_key,
            dialect=dialect,
            source_engine=source_engine,
            target_engine=target_engine,
        )
        docs = generator.format_for_vanna(schema)
        for doc in docs:
            vn.train(documentation=doc)
        logger.info("Trained %d LLM-description docs", len(docs))
    except Exception as exc:
        logger.warning("Description training failed: %s", exc)


def _train_fk_docs(vn, source_engine: Engine, target_engine: Engine, schema: str, dialect: str) -> None:
    try:
        from enrichment.fk_inference import FKInference
        fk = FKInference(
            source_url="",
            target_url="",
            dialect=dialect,
            source_engine=source_engine,
            target_engine=target_engine,
        )
        docs = fk.format_for_vanna(schema)
        for doc in docs:
            vn.train(documentation=doc)
        logger.info("Trained %d FK relationship docs", len(docs))
    except Exception as exc:
        logger.warning("FK relationship training failed: %s", exc)


def _train_domain_docs(vn) -> None:
    docs = [
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
    for doc in docs:
        vn.train(documentation=doc)
    logger.info("Trained %d domain docs", len(docs))


def _train_sql_examples(vn, schema: str) -> None:
    s = schema
    examples = [
        ("Show me all active customers",
         f"SELECT * FROM [{s}].[tbl_cust] WHERE [stat_cd] = 'ACTIVE'"),
        ("How many accounts does each customer have?",
         f"SELECT [cust_no], COUNT(*) as account_count FROM [{s}].[tbl_acct] GROUP BY [cust_no] ORDER BY account_count DESC"),
        ("What is the total loan portfolio by product category?",
         f"SELECT lp.[prod_categ], COUNT(l.[loan_no]) as loan_count, SUM(l.[outst_princ]) as total_outstanding FROM [{s}].[tbl_loan] l JOIN [{s}].[tbl_loan_prod] lp ON l.[prod_cd] = lp.[prod_cd] WHERE l.[stat_cd] = 'ACTIVE' GROUP BY lp.[prod_categ] ORDER BY total_outstanding DESC"),
        ("Show me all non-performing loans with customer details",
         f"SELECT c.[cust_nm], l.[loan_no], l.[loan_amt], l.[outst_princ], l.[overdue_amt], l.[overdue_days] FROM [{s}].[tbl_loan] l JOIN [{s}].[tbl_cust] c ON l.[cust_no] = c.[cust_no] WHERE l.[npl_flag] = 'Y'"),
        ("What are the top 5 accounts by current balance?",
         f"SELECT TOP 5 a.[acct_no], c.[cust_nm], a.[ccy_cd], a.[cur_bal] FROM [{s}].[tbl_acct] a JOIN [{s}].[tbl_cust] c ON a.[cust_no] = c.[cust_no] WHERE a.[stat_cd] = 'OPEN' ORDER BY a.[cur_bal] DESC"),
        ("Show transactions for account ACC-001 in February 2025",
         f"SELECT t.[txn_dt], t.[txn_amt], t.[dr_cr_ind], t.[descr], tp.[txn_tp_nm] FROM [{s}].[tbl_txn] t JOIN [{s}].[tbl_txn_tp] tp ON t.[txn_tp_cd] = tp.[txn_tp_cd] WHERE t.[acct_no] = 'MD24AG000000000001MDL' AND t.[txn_dt] >= '2025-02-01' AND t.[txn_dt] < '2025-03-01' ORDER BY t.[txn_dt]"),
        ("Which branches have more than 3 employees?",
         f"SELECT b.[br_nm], COUNT(e.[emp_no]) as emp_count FROM [{s}].[tbl_br] b JOIN [{s}].[tbl_emp] e ON b.[br_cd] = e.[br_cd] WHERE e.[stat_cd] = 1 GROUP BY b.[br_nm] HAVING COUNT(e.[emp_no]) > 3"),
        ("Show me customers with both loans and cards",
         f"SELECT DISTINCT c.[cust_no], c.[cust_nm] FROM [{s}].[tbl_cust] c WHERE c.[cust_no] IN (SELECT [cust_no] FROM [{s}].[tbl_loan]) AND c.[cust_no] IN (SELECT [cust_no] FROM [{s}].[tbl_card])"),
    ]
    for question, sql in examples:
        vn.train(question=question, sql=sql)
    logger.info("Trained %d SQL examples", len(examples))

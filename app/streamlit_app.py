"""DB-Navigator AI - Streamlit Chat Interface.

Dual-database architecture:
  - SOURCE (MS SQL Server): DDL extraction, SQL execution, enrichment source
  - TARGET (PostgreSQL): enrichment metadata, pgvector, app data

Training pipeline:
  1. DDL from SQL Server via INFORMATION_SCHEMA
  2. Enrichment documentation (sample values, column stats) via metadata_extractor
  3. FK relationship documentation via fk_inference
  4. Manual domain documentation (banking terminology, conventions)
  5. SQL examples (question-SQL pairs for few-shot learning)
"""
import logging
import streamlit as st
from vanna.openai import OpenAI_Chat
from vanna.chromadb import ChromaDB_VectorStore
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from config import (
    SOURCE_DATABASE_URL, DATABASE_URL, OPENAI_API_KEY, BANK_SCHEMA,
)
MSSQL_URL = SOURCE_DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Page config ---
st.set_page_config(
    page_title="DB-Navigator AI",
    page_icon="🧭",
    layout="wide",
)

st.title("DB-Navigator AI")
st.caption("Ask questions about the bank database in natural language.")


# ---------------------------------------------------------------------------
# Initialization (cached - runs once per session)
# ---------------------------------------------------------------------------

@st.cache_resource
def init_vanna():
    """Set up Vanna with OpenAI + ChromaDB."""

    class DBNavigator(ChromaDB_VectorStore, OpenAI_Chat):
        def __init__(self, config=None):
            ChromaDB_VectorStore.__init__(
                self, config={"persist_directory": "/tmp/vanna_chroma"}
            )
            OpenAI_Chat.__init__(
                self, config={"api_key": OPENAI_API_KEY, "model": "gpt-4o-mini"}
            )

    return DBNavigator()


@st.cache_resource
def get_source_engine() -> Engine:
    """SQL Server engine for DDL extraction and query execution."""
    return create_engine(MSSQL_URL)


@st.cache_resource
def get_target_engine() -> Engine:
    """PostgreSQL engine for enrichment metadata."""
    return create_engine(DATABASE_URL)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_vanna_if_needed(vn):
    """Train Vanna with DDL, enrichment docs, domain docs, and SQL examples.

    Only runs if no training data exists yet. To retrain, clear the
    ChromaDB persist directory and restart.
    """
    existing = vn.get_training_data()
    if existing is not None and len(existing) > 0:
        return

    source = get_source_engine()

    # ---- 1. DDL from SQL Server ----
    _train_ddl(vn, source)

    # ---- 2. Enrichment documentation (metadata extractor + FK inference) ----
    _train_enrichment_docs(vn, source)

    # ---- 3. Manual domain documentation ----
    _train_domain_docs(vn)

    # ---- 4. SQL examples (T-SQL syntax) ----
    _train_sql_examples(vn)


def _train_ddl(vn, engine: Engine):
    """Extract DDL from SQL Server and train Vanna."""
    with engine.connect() as conn:
        tables = conn.execute(text("""
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = :schema
                AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """), {"schema": BANK_SCHEMA}).fetchall()

        for (table_name,) in tables:
            cols = conn.execute(text("""
                SELECT
                    COLUMN_NAME,
                    DATA_TYPE,
                    IS_NULLABLE,
                    CHARACTER_MAXIMUM_LENGTH,
                    NUMERIC_PRECISION
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = :schema
                    AND TABLE_NAME = :table
                ORDER BY ORDINAL_POSITION
            """), {"schema": BANK_SCHEMA, "table": table_name}).fetchall()

            ddl_lines = [f"CREATE TABLE [{BANK_SCHEMA}].[{table_name}] ("]
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
            ddl = "\n".join(ddl_lines)

            vn.train(ddl=ddl)

    logger.info("Trained Vanna with DDL for %d tables", len(tables))


def _train_enrichment_docs(vn, engine: Engine):
    """Generate and train enrichment documentation from live database.

    Runs metadata extractor and FK inference on-the-fly rather than
    reading from PostgreSQL, so training always reflects current schema.
    """
    from enrichment.metadata_extractor import MetadataExtractor
    from enrichment.fk_inference import FKInference

    target = get_target_engine()

    # -- Metadata extractor: sample values + column stats --
    try:
        extractor = MetadataExtractor(
            source_url=MSSQL_URL,
            target_url=DATABASE_URL,
            source_engine=engine,
            target_engine=target,
        )
        meta_docs = extractor.format_for_vanna(BANK_SCHEMA)
        for doc in meta_docs:
            vn.train(documentation=doc)
        logger.info("Trained Vanna with %d metadata enrichment docs", len(meta_docs))
    except Exception as e:
        logger.warning("Metadata enrichment training failed: %s", e)

    # -- FK inference: relationship documentation --
    try:
        dialect = "mssql" if "mssql" in MSSQL_URL else "postgresql"
        fk_engine = FKInference(
            source_url=MSSQL_URL,
            target_url=DATABASE_URL,
            dialect=dialect,
            source_engine=engine,
            target_engine=target,
        )
        fk_docs = fk_engine.format_for_vanna(BANK_SCHEMA)
        for doc in fk_docs:
            vn.train(documentation=doc)
        logger.info("Trained Vanna with %d FK relationship docs", len(fk_docs))
    except Exception as e:
        logger.warning("FK inference training failed: %s", e)


def _train_domain_docs(vn):
    """Train with manual domain-specific documentation.

    These cover banking terminology and conventions that can't be
    inferred automatically from schema structure alone.
    """
    docs = [
        "This is a Moldovan bank database (Moldova Agroindbank / MAIB). "
        "All SQL must use T-SQL syntax (SQL Server). Use TOP instead of LIMIT.",

        "cust_tp 'PF' means Persoana Fizica (individual customer), "
        "'PJ' means Persoana Juridica (company/legal entity).",

        "Account status values in tbl_acct.stat_cd: "
        "'OPEN' = active account, 'FROZEN' = frozen account, "
        "'CLOSED' = closed account, 'DORMANT' = dormant/inactive account.",

        "Customer status values in tbl_cust.stat_cd: "
        "'ACTIVE' = active customer, 'DORMANT' = dormant customer, "
        "'BLOCKED' = blocked customer.",

        "Branch status values in tbl_br.stat_cd: "
        "1 = active branch, 0 = closed branch (uses integers, not strings).",

        "Employee status values in tbl_emp.stat_cd: "
        "1 = active employee, 0 = terminated (uses integers, not strings).",

        "ccy_cd is currency code: MDL = Moldovan Leu, USD = US Dollar, "
        "EUR = Euro, RON = Romanian Leu.",

        "dr_cr_ind: 'D' = debit (money out of account), "
        "'C' = credit (money into account).",

        "npl_flag: 'Y' = non-performing loan (overdue > 90 days), "
        "'N' = performing loan.",

        "IDNP = Numarul de Identificare de Stat al Persoanei "
        "(Moldova national ID number for individuals).",

        "IDNO = Numar de Identificare de Stat al Organizatiei "
        "(company registration number for legal entities).",
    ]

    for doc in docs:
        vn.train(documentation=doc)

    logger.info("Trained Vanna with %d domain documentation strings", len(docs))


def _train_sql_examples(vn):
    """Train with curated SQL examples in T-SQL syntax.

    These provide few-shot demonstrations of correct query patterns.
    Note: uses TOP (T-SQL) instead of LIMIT (PostgreSQL).
    """
    s = BANK_SCHEMA  # shorthand

    examples = [
        (
            "Show me all active customers",
            f"SELECT * FROM [{s}].[tbl_cust] WHERE stat_cd = 'ACTIVE'"
        ),
        (
            "How many accounts does each customer have?",
            f"SELECT cust_no, COUNT(*) AS account_count "
            f"FROM [{s}].[tbl_acct] "
            f"GROUP BY cust_no ORDER BY account_count DESC"
        ),
        (
            "What is the total loan portfolio by product category?",
            f"SELECT lp.prod_categ, COUNT(l.loan_no) AS loan_count, "
            f"SUM(l.outst_princ) AS total_outstanding "
            f"FROM [{s}].[tbl_loan] l "
            f"JOIN [{s}].[tbl_loan_prod] lp ON l.prod_cd = lp.prod_cd "
            f"WHERE l.stat_cd = 'ACTIVE' "
            f"GROUP BY lp.prod_categ ORDER BY total_outstanding DESC"
        ),
        (
            "Show me all non-performing loans with customer details",
            f"SELECT c.cust_nm, l.loan_no, l.loan_amt, l.outst_princ, "
            f"l.overdue_amt, l.overdue_days "
            f"FROM [{s}].[tbl_loan] l "
            f"JOIN [{s}].[tbl_cust] c ON l.cust_no = c.cust_no "
            f"WHERE l.npl_flag = 'Y'"
        ),
        (
            "What are the top 5 accounts by current balance?",
            f"SELECT TOP 5 a.acct_no, c.cust_nm, a.ccy_cd, a.cur_bal "
            f"FROM [{s}].[tbl_acct] a "
            f"JOIN [{s}].[tbl_cust] c ON a.cust_no = c.cust_no "
            f"WHERE a.stat_cd = 'OPEN' "
            f"ORDER BY a.cur_bal DESC"
        ),
        (
            "Show me dormant accounts",
            f"SELECT a.acct_no, c.cust_nm, a.ccy_cd, a.cur_bal, a.last_txn_dt "
            f"FROM [{s}].[tbl_acct] a "
            f"JOIN [{s}].[tbl_cust] c ON a.cust_no = c.cust_no "
            f"WHERE a.stat_cd = 'DORMANT'"
        ),
        (
            "Show the top 3 customers by total balance across all accounts",
            f"SELECT TOP 3 c.cust_no, c.cust_nm, SUM(a.cur_bal) AS total_balance "
            f"FROM [{s}].[tbl_acct] a "
            f"JOIN [{s}].[tbl_cust] c ON a.cust_no = c.cust_no "
            f"GROUP BY c.cust_no, c.cust_nm "
            f"ORDER BY total_balance DESC"
        ),
        (
            "Which loans have collateral value less than outstanding principal?",
            f"SELECT l.loan_no, l.outst_princ, "
            f"SUM(co.appraisal_val) AS total_collateral "
            f"FROM [{s}].[tbl_loan] l "
            f"JOIN [{s}].[tbl_coll] co ON l.loan_no = co.loan_no "
            f"WHERE l.stat_cd = 'ACTIVE' "
            f"GROUP BY l.loan_no, l.outst_princ "
            f"HAVING SUM(co.appraisal_val) < l.outst_princ"
        ),
    ]

    for question, sql in examples:
        vn.train(question=question, sql=sql)

    logger.info("Trained Vanna with %d SQL examples", len(examples))


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

try:
    vn = init_vanna()
    source_engine = get_source_engine()
    train_vanna_if_needed(vn)
except Exception as e:
    st.error(f"Initialization error: {e}")
    st.info("Make sure Docker containers are running and OPENAI_API_KEY is set in .env")
    st.stop()

# Chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sql" in msg:
            st.code(msg["sql"], language="sql")
        if "df" in msg and msg["df"] is not None:
            st.dataframe(msg["df"], use_container_width=True)

def fix_tsql_syntax(sql: str) -> str:
    """Post-process generated SQL to fix common T-SQL syntax issues."""
    import re
    match = re.search(r'\bLIMIT\s+(\d+)\s*;?\s*$', sql, re.IGNORECASE)
    if match:
        n = match.group(1)
        sql = re.sub(r'\bLIMIT\s+\d+\s*;?\s*$', '', sql, flags=re.IGNORECASE).strip()
        sql = re.sub(r'^(SELECT)\b', f'SELECT TOP {n}', sql, count=1, flags=re.IGNORECASE)
        if not sql.endswith(';'):
            sql += ';'
    return sql

# Chat input
if prompt := st.chat_input("Ask a question about the bank database..."):
    # Show user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generate and execute SQL
    with st.chat_message("assistant"):
        with st.spinner("Generating SQL..."):
            try:
                sql = fix_tsql_syntax(vn.generate_sql(question=prompt))
                st.code(sql, language="sql")

                # Execute against SQL Server
                with source_engine.connect() as conn:
                    df = pd.read_sql(text(sql), conn)

                if len(df) == 0:
                    st.info("Query returned no results.")
                    result_msg = {
                        "role": "assistant",
                        "content": "Query executed successfully but returned no results.",
                        "sql": sql,
                        "df": None,
                    }
                else:
                    st.success(f"Returned {len(df)} rows")
                    st.dataframe(df, use_container_width=True)
                    result_msg = {
                        "role": "assistant",
                        "content": f"Returned {len(df)} rows",
                        "sql": sql,
                        "df": df,
                    }

            except Exception as e:
                st.error(f"Error: {e}")
                result_msg = {
                    "role": "assistant",
                    "content": f"Error: {e}",
                    "sql": sql if "sql" in dir() else None,
                }

        st.session_state.messages.append(result_msg)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("About")
    st.markdown("""
    **DB-Navigator AI** generates SQL from natural language
    questions using RAG-powered LLMs.

    Built for ASE Bucharest undergraduate thesis.
    """)

    st.header("Training Data")
    try:
        td = vn.get_training_data()
        if td is not None:
            st.metric("DDL entries", len(td[td["training_data_type"] == "ddl"]))
            st.metric("Documentation", len(td[td["training_data_type"] == "documentation"]))
            st.metric("SQL examples", len(td[td["training_data_type"] == "sql"]))
    except Exception:
        st.caption("Training data not yet loaded")

    st.header("System Info")
    st.caption(f"Schema: {BANK_SCHEMA}")
    st.caption("Source: MS SQL Server")
    st.caption("LLM: GPT-4o-mini")
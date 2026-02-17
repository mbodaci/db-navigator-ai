"""DB-Navigator AI - Streamlit Chat Interface.

Minimal viable UI: text input -> Vanna.ai -> SQL -> results.
"""
import streamlit as st
import vanna
from vanna.openai import OpenAI_Chat
from vanna.chromadb import ChromaDB_VectorStore
import pandas as pd
from sqlalchemy import create_engine, text
from config import DATABASE_URL, OPENAI_API_KEY, BANK_SCHEMA

# --- Page config ---
st.set_page_config(
    page_title="DB-Navigator AI",
    layout="wide"
)

st.title("DB-Navigator AI")
st.caption("Ask questions about the bank database in natural language.")


# --- Initialize Vanna (cached so it only runs once) ---
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

    vn = DBNavigator()
    return vn


@st.cache_resource
def get_engine():
    """Create SQLAlchemy engine."""
    return create_engine(DATABASE_URL)


def train_vanna_if_needed(vn):
    """Train Vanna with bank schema DDL and documentation.
    
    Only runs if no training data exists yet.
    """
    # Check if already trained (simple heuristic)
    existing = vn.get_training_data()
    if existing is not None and len(existing) > 0:
        return

    engine = get_engine()

    # 1. Train with DDL from the bank schema
    with engine.connect() as conn:
        tables = conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = :schema
            ORDER BY table_name
        """), {"schema": BANK_SCHEMA}).fetchall()

        for (table_name,) in tables:
            # Get CREATE TABLE-like DDL
            cols = conn.execute(text("""
                SELECT column_name, data_type, is_nullable,
                       character_maximum_length, numeric_precision
                FROM information_schema.columns
                WHERE table_schema = :schema AND table_name = :table
                ORDER BY ordinal_position
            """), {"schema": BANK_SCHEMA, "table": table_name}).fetchall()

            ddl_lines = [f"CREATE TABLE {BANK_SCHEMA}.{table_name} ("]
            for col_name, dtype, nullable, max_len, num_prec in cols:
                type_str = dtype.upper()
                if max_len:
                    type_str += f"({max_len})"
                elif num_prec:
                    type_str += f"({num_prec})"
                null_str = "" if nullable == "YES" else " NOT NULL"
                ddl_lines.append(f"    {col_name} {type_str}{null_str},")
            ddl_lines[-1] = ddl_lines[-1].rstrip(",")
            ddl_lines.append(");")
            ddl = "\n".join(ddl_lines)

            vn.train(ddl=ddl)

    # 2. Train with basic documentation
    docs = [
        "The bank schema contains tables for Moldova Agroindbank (MAIB), Moldova's largest bank.",
        "cust_tp 'PF' means Persoana Fizica (individual), 'PJ' means Persoana Juridica (company).",
        "stat_cd values: 1 or 'ACTIVE' = active, 0 or 'CLOSED' = closed. Some tables use integers, others use strings.",
        "ccy_cd is currency code: MDL = Moldovan Leu, USD = US Dollar, EUR = Euro, RON = Romanian Leu.",
        "dr_cr_ind: 'D' = debit (money out), 'C' = credit (money in).",
        "npl_flag: 'Y' = non-performing loan (overdue > 90 days), 'N' = performing.",
        "IDNP = Numarul de Identificare de Stat al Persoanei (Moldova national ID).",
        "IDNO = company registration number.",
        "br_cd links to branch codes in tbl_br. All customer, account and employee records reference a branch.",
        "tbl_txn contains all financial transactions. Use acct_no to join to tbl_acct, and txn_tp_cd to join to tbl_txn_tp.",
        "tbl_loan tracks all loans. disb_acct_no and repay_acct_no link to accounts in tbl_acct.",
        "tbl_coll stores collateral for loans. Join via loan_no to tbl_loan.",
        "tbl_guar stores loan guarantors. guar_cust_no may be NULL if guarantor is not an existing bank customer.",
    ]
    for doc in docs:
        vn.train(documentation=doc)

    # 3. Train with a few SQL examples
    examples = [
        ("Show me all active customers",
         f"SELECT * FROM {BANK_SCHEMA}.tbl_cust WHERE stat_cd = 'ACTIVE'"),
        ("How many accounts does each customer have?",
         f"SELECT cust_no, COUNT(*) as account_count FROM {BANK_SCHEMA}.tbl_acct GROUP BY cust_no ORDER BY account_count DESC"),
        ("What is the total loan portfolio by product category?",
         f"SELECT lp.prod_categ, COUNT(l.loan_no) as loan_count, SUM(l.outst_princ) as total_outstanding FROM {BANK_SCHEMA}.tbl_loan l JOIN {BANK_SCHEMA}.tbl_loan_prod lp ON l.prod_cd = lp.prod_cd WHERE l.stat_cd = 'ACTIVE' GROUP BY lp.prod_categ ORDER BY total_outstanding DESC"),
        ("Show me all non-performing loans with customer details",
         f"SELECT c.cust_nm, l.loan_no, l.loan_amt, l.outst_princ, l.overdue_amt, l.overdue_days FROM {BANK_SCHEMA}.tbl_loan l JOIN {BANK_SCHEMA}.tbl_cust c ON l.cust_no = c.cust_no WHERE l.npl_flag = 'Y'"),
        ("What are the top 5 accounts by current balance?",
         f"SELECT a.acct_no, c.cust_nm, a.ccy_cd, a.cur_bal FROM {BANK_SCHEMA}.tbl_acct a JOIN {BANK_SCHEMA}.tbl_cust c ON a.cust_no = c.cust_no WHERE a.stat_cd = 'OPEN' ORDER BY a.cur_bal DESC LIMIT 5"),
    ]
    for question, sql in examples:
        vn.train(question=question, sql=sql)


# --- Main app ---
try:
    vn = init_vanna()
    engine = get_engine()
    train_vanna_if_needed(vn)
except Exception as e:
    st.error(f"Initialization error: {e}")
    st.info("Make sure PostgreSQL is running and OPENAI_API_KEY is set in .env")
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

# Chat input
if prompt := st.chat_input("Ask a question about the bank database..."):
    # Show user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generate SQL
    with st.chat_message("assistant"):
        with st.spinner("Generating SQL..."):
            try:
                sql = vn.generate_sql(question=prompt)
                st.code(sql, language="sql")

                # Execute SQL
                with engine.connect() as conn:
                    df = pd.read_sql(text(sql), conn)

                if len(df) == 0:
                    st.info("Query returned no results.")
                    result_msg = {"role": "assistant", "content": "Query executed successfully but returned no results.", "sql": sql, "df": None}
                else:
                    st.success(f"Returned {len(df)} rows")
                    st.dataframe(df, use_container_width=True)
                    result_msg = {"role": "assistant", "content": f"Returned {len(df)} rows", "sql": sql, "df": df}

            except Exception as e:
                st.error(f"Error: {e}")
                result_msg = {"role": "assistant", "content": f"Error: {e}", "sql": sql if 'sql' in dir() else None}

        st.session_state.messages.append(result_msg)

# Sidebar
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
    except:
        st.caption("Training data not yet loaded")

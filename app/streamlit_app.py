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
from upload.streamlit_upload import (
    render_upload_section, get_active_vanna, get_active_engine, is_upload_active,
)
from config import (
    SOURCE_DATABASE_URL, DATABASE_URL, OPENAI_API_KEY, BANK_SCHEMA,
)
MSSQL_URL = SOURCE_DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Page config ---
st.set_page_config(
    page_title="DB-Navigator AI",
    layout="wide",
)

st.markdown(
    """
    <style>
      :root { --navy:#14213d; --orange:#fca311; --grey:#e5e5e5; --ink:#000000; }
      #MainMenu {visibility:hidden;}
      footer {visibility:hidden;}
      [data-testid="stToolbar"] {display:none;}
      [data-testid="stDecoration"] {display:none;}
      [data-testid="stStatusWidget"] {display:none;}
      .block-container { padding-top:2.2rem; max-width:1120px; }
      .dbnav-hero {
        background:var(--navy); border-radius:14px; padding:24px 30px;
        margin-bottom:14px; border-left:6px solid var(--orange);
      }
      .dbnav-hero h1 { color:#ffffff; margin:0; font-size:1.95rem; font-weight:700; letter-spacing:.3px; }
      .dbnav-hero p { color:var(--grey); margin:.45rem 0 0; font-size:1.02rem; }
      .dbnav-accent { color:var(--orange); }
      .dbnav-pipe {
        display:flex; flex-wrap:wrap; gap:.45rem; align-items:center;
        margin:0 2px 20px; color:var(--navy); font-size:.8rem; font-weight:600;
      }
      .dbnav-pipe .step { background:#ffffff; border:1px solid var(--grey); border-radius:20px; padding:3px 12px; }
      .dbnav-pipe .arrow { color:var(--orange); font-weight:800; }
      .stButton > button {
        border:1.5px solid var(--navy); color:var(--navy); background:#ffffff;
        border-radius:10px; font-weight:600; transition:all .15s ease;
      }
      .stButton > button:hover { background:var(--navy); color:#ffffff; border-color:var(--navy); }
      [data-testid="stSidebar"] { border-right:3px solid var(--orange); }
      [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color:var(--navy); }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="dbnav-hero">'
    '<h1>DB-Navigator <span class="dbnav-accent">AI</span></h1>'
    '<p>Pune orice întrebare despre baza de date a băncii în limbaj natural - sistemul scrie și execută automat interogarea SQL.</p>'
    '</div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="dbnav-pipe">'
    '<span class="step">Limbaj natural</span><span class="arrow">&#8594;</span>'
    '<span class="step">Regăsire pe baza schemei (RAG)</span><span class="arrow">&#8594;</span>'
    '<span class="step">GPT-4o-mini</span><span class="arrow">&#8594;</span>'
    '<span class="step">T-SQL</span><span class="arrow">&#8594;</span>'
    '<span class="step">SQL Server</span><span class="arrow">&#8594;</span>'
    '<span class="step">Rezultate</span>'
    '</div>',
    unsafe_allow_html=True,
)


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
    st.error(f"Eroare de inițializare: {e}")
    st.info("Asigură-te că rulează containerele Docker și că OPENAI_API_KEY este setat în .env")
    st.stop()

# Chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Example questions (shown only before the first question, so a demo can start
# with a click instead of typing live).
EXAMPLE_QUESTIONS = [
    "Arată toți clienții activi",
    "Care sunt primele 5 conturi după soldul curent?",
    "Câte conturi are fiecare client?",
    "Care este portofoliul total de credite pe categorii de produse?",
]


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


def fix_standard_syntax(sql: str) -> str:
    """Convert T-SQL artifacts to standard SQL for uploaded SQLite/PostgreSQL DBs.

    The model sometimes emits 'SELECT TOP N ...' (learned from the bank DB's
    T-SQL documentation) even for an uploaded database. Rewrite it to the
    standard 'SELECT ... LIMIT N' that SQLite and PostgreSQL expect.
    """
    import re
    match = re.search(r'^\s*SELECT\s+TOP\s+(\d+)\b', sql, re.IGNORECASE)
    if match:
        n = match.group(1)
        sql = re.sub(r'^(\s*SELECT)\s+TOP\s+\d+\b', r'\1', sql, count=1, flags=re.IGNORECASE).strip()
        sql = sql.rstrip(';').rstrip()
        sql = f"{sql} LIMIT {n}"
    return sql


def _save_feedback(msg: dict, rating: str, comment: str) -> None:
    """Persist a user's rating of a generated query to Postgres.

    Best-effort: any failure is logged and swallowed so feedback can never
    break the demo.
    """
    try:
        engine = get_target_engine()
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS public.user_feedback ("
                "id SERIAL PRIMARY KEY, "
                "created_at TIMESTAMP DEFAULT now(), "
                "question TEXT, generated_sql TEXT, rating TEXT, comment TEXT)"
            ))
            conn.execute(
                text(
                    "INSERT INTO public.user_feedback "
                    "(question, generated_sql, rating, comment) "
                    "VALUES (:q, :s, :r, :c)"
                ),
                {
                    "q": msg.get("question"),
                    "s": msg.get("sql"),
                    "r": rating,
                    "c": comment,
                },
            )
    except Exception as exc:
        logger.warning("Could not save feedback: %s", exc)


def render_feedback(idx: int, msg: dict) -> None:
    """Like / dislike controls under an assistant answer.

    'Greșit' opens a free-text box so the user can describe what was missed
    (required tables, columns, filters, wrong values). State is kept per
    message in st.session_state so it survives reruns.
    """
    state = st.session_state.get(f"fb_{idx}", "none")
    if state == "good":
        st.caption("Notat ca util. Mulțumim pentru feedback.")
        return
    if state == "done":
        st.caption("Feedback trimis. Mulțumim.")
        return
    if state == "bad_open":
        note = st.text_area(
            "Ce a lipsit sau ce a greșit? (ex: tabele/coloane necesare, filtre, valori)",
            key=f"fb_note_{idx}",
            placeholder="Detalii opționale...",
        )
        b1, b2, _ = st.columns([1, 1, 5])
        if b1.button("Trimite", key=f"fb_submit_{idx}"):
            _save_feedback(msg, "negativ", note)
            st.session_state[f"fb_{idx}"] = "done"
            st.rerun()
        if b2.button("Anulează", key=f"fb_cancel_{idx}"):
            st.session_state[f"fb_{idx}"] = "none"
            st.rerun()
        return
    c1, c2, _ = st.columns([1, 1, 6])
    if c1.button("Util", key=f"fb_good_{idx}"):
        _save_feedback(msg, "pozitiv", "")
        st.session_state[f"fb_{idx}"] = "good"
        st.rerun()
    if c2.button("Greșit", key=f"fb_bad_{idx}"):
        st.session_state[f"fb_{idx}"] = "bad_open"
        st.rerun()


def render_message(idx: int, msg: dict) -> None:
    """Render one chat message; assistant answers also get feedback controls."""
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.markdown(msg["content"])
            return
        if msg.get("sql"):
            st.code(msg["sql"], language="sql")
        if msg.get("df") is not None:
            st.dataframe(msg["df"], use_container_width=True)
            st.caption(msg["content"])
        else:
            st.markdown(msg["content"])
        if msg.get("sql"):
            render_feedback(idx, msg)


# Example chips: only before the first question, and not on the rerun that is
# about to process a clicked example (dbnav_pending is set then) - otherwise the
# list would linger above the first answer.
if not st.session_state.messages and "dbnav_pending" not in st.session_state:
    st.markdown("###### Încearcă un exemplu")
    _ex_cols = st.columns(2)
    for _i, _ex in enumerate(EXAMPLE_QUESTIONS):
        if _ex_cols[_i % 2].button(_ex, key=f"dbnav_example_{_i}", use_container_width=True):
            st.session_state.dbnav_pending = _ex
            st.rerun()

# Render the existing conversation
for _idx, _msg in enumerate(st.session_state.messages):
    render_message(_idx, _msg)

# Chat input (typed) or a clicked example question
_typed = st.chat_input("Pune o întrebare despre baza de date a băncii...")
question = _typed or st.session_state.pop("dbnav_pending", None)
if question:
    user_msg = {"role": "user", "content": question}
    st.session_state.messages.append(user_msg)
    render_message(len(st.session_state.messages) - 1, user_msg)

    with st.spinner("Se generează interogarea SQL..."):
        try:
            # Route through the uploaded database if one is active,
            # otherwise use the default synthetic bank database.
            active_vn = get_active_vanna(vn)
            active_engine = get_active_engine(source_engine)

            raw_sql = active_vn.generate_sql(question=question)
            # Default bank DB (SQL Server): convert LIMIT -> TOP.
            # Uploaded SQLite/PostgreSQL DB: convert any stray TOP -> LIMIT.
            if is_upload_active():
                sql = fix_standard_syntax(raw_sql)
            else:
                sql = fix_tsql_syntax(raw_sql)

            with active_engine.connect() as conn:
                df = pd.read_sql(text(sql), conn)

            if len(df) == 0:
                assistant_msg = {
                    "role": "assistant",
                    "content": "Interogarea s-a executat cu succes, dar nu a returnat rezultate.",
                    "sql": sql,
                    "df": None,
                    "question": question,
                }
            else:
                assistant_msg = {
                    "role": "assistant",
                    "content": f"S-au returnat {len(df)} rânduri",
                    "sql": sql,
                    "df": df,
                    "question": question,
                }
        except Exception as e:
            assistant_msg = {
                "role": "assistant",
                "content": f"Eroare: {e}",
                "sql": sql if "sql" in dir() else None,
                "question": question,
            }

    st.session_state.messages.append(assistant_msg)
    render_message(len(st.session_state.messages) - 1, assistant_msg)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Despre")
    st.markdown("""
    **DB-Navigator AI** generează interogări SQL din întrebări
    în limbaj natural, folosind modele LLM cu RAG.

    Realizat pentru lucrarea de licență, ASE București.
    """)

    st.header("Date de antrenament")
    try:
        td = vn.get_training_data()
        if td is not None:
            st.metric("Intrări DDL", len(td[td["training_data_type"] == "ddl"]))
            st.metric("Documentație", len(td[td["training_data_type"] == "documentation"]))
            st.metric("Exemple SQL", len(td[td["training_data_type"] == "sql"]))
    except Exception:
        st.caption("Datele de antrenament nu sunt încă încărcate")

    st.header("Informații sistem")
    st.caption(f"Schemă: {BANK_SCHEMA}")
    st.caption("Sursă: MS SQL Server")
    st.caption("LLM: GPT-4o-mini")
    st.divider()
    render_upload_section()
"""
upload_handler.py - Handles user-uploaded databases (SQLite, SQL dump, or ZIP).

ZIP convention (the structure users must follow):
    my_database.zip
    |-- database.sqlite   (or database.db / database.sqlite3 / database.sql)  -> required
    |-- examples.jsonl    -> optional, question-SQL pairs for few-shot

examples.jsonl format (one JSON object per line, exactly two keys):
    {"question": "How many customers?", "sql": "SELECT COUNT(*) FROM customers"}

Why examples matter: the ablation study showed full enrichment WITHOUT examples
sits near baseline (Config E ~69.8%); adding question-SQL examples recovered the
top result (Config F ~76%). Uploaded databases get enrichment automatically, but
without user-supplied examples they miss the few-shot component, so accuracy is
lower. Supplying examples.jsonl closes that gap.

Import paths use no 'app.' prefix to match the Docker working directory (/app).
"""

import re
import json
import uuid
import shutil
import sqlite3
import zipfile
import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config import DATABASE_URL, OPENAI_API_KEY

logger = logging.getLogger(__name__)

# ============================================================
# Configuration
# ============================================================

MAX_FILE_SIZE_MB = 100
MAX_TABLES = 200
MAX_COLUMNS_PER_TABLE = 500
MAX_EXAMPLES = 100
SESSION_TIMEOUT_MINUTES = 30
TEMP_DIR_BASE = Path(tempfile.gettempdir()) / "dbnavigator_uploads"

# Accepted names for the database file inside a zip (priority order)
DB_FILE_CANDIDATES = [
    "database.sqlite", "database.db", "database.sqlite3", "database.sql",
]
EXAMPLES_FILENAME = "examples.jsonl"

DB_EXTENSIONS = {".db", ".sqlite", ".sqlite3", ".sql"}
SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}

BLOCKED_SQL_PATTERNS = [
    r"^\s*DROP\s+", r"^\s*ALTER\s+", r"^\s*TRUNCATE\s+",
    r"^\s*GRANT\s+", r"^\s*REVOKE\s+", r"^\s*CREATE\s+USER\s+",
    r"^\s*CREATE\s+ROLE\s+", r"^\s*CREATE\s+EXTENSION\s+",
    r"^\s*COPY\s+.*FROM\s+", r"\bpg_read_server_files\b",
    r"\bpg_ls_dir\b", r"\bxp_cmdshell\b",
]


# ============================================================
# Session tracking
# ============================================================

class UploadSession:
    def __init__(self, session_id: str, db_type: str):
        self.session_id = session_id
        self.db_type = db_type  # 'sqlite' or 'sql_dump'
        self.created_at = datetime.now()
        self.expires_at = self.created_at + timedelta(minutes=SESSION_TIMEOUT_MINUTES)
        self.schema_name = f"upload_{session_id.replace('-', '_')[:16]}"
        self.sqlite_path: Optional[Path] = None
        self.extract_dir: Optional[Path] = None
        self.vanna_instance = None
        self.engine: Optional[Engine] = None
        self.table_count = 0
        self.column_count = 0
        self.example_count = 0

    @property
    def dialect(self) -> str:
        return "sqlite" if self.db_type == "sqlite" else "postgresql"

    def is_expired(self) -> bool:
        return datetime.now() > self.expires_at


_active_sessions: dict = {}


# ============================================================
# Main entry point
# ============================================================

def handle_upload(file_bytes: bytes, filename: str, load_examples: bool = False):
    """Process an uploaded database file end-to-end.

    Accepts a raw database file (.sqlite/.db/.sqlite3/.sql) OR a .zip following
    the documented convention. `load_examples` only applies to zip uploads and
    tells the handler to look for examples.jsonl inside the archive.

    Returns (session, error_message). If session is None, error_message explains
    the failure.
    """
    error = _validate_upload(file_bytes, filename)
    if error:
        return None, error

    ext = Path(filename).suffix.lower()
    session_id = str(uuid.uuid4())

    try:
        if ext == ".zip":
            return _handle_zip(session_id, file_bytes, load_examples)
        db_type = "sqlite" if ext in SQLITE_EXTENSIONS else "sql_dump"
        session = UploadSession(session_id, db_type)
        if db_type == "sqlite":
            session.engine = _materialize_sqlite(session, file_bytes)
        else:
            session.engine = _materialize_sql_dump(session, file_bytes)
        return _finalize(session, examples=None)

    except Exception as e:
        logger.exception("Upload processing failed")
        cleanup_session(session_id)
        return None, f"Processing failed: {type(e).__name__}: {e}"


def _handle_zip(session_id: str, file_bytes: bytes, load_examples: bool):
    """Extract a zip, locate the database file and optional examples.jsonl."""
    TEMP_DIR_BASE.mkdir(parents=True, exist_ok=True)
    extract_dir = TEMP_DIR_BASE / f"zip_{session_id}"
    extract_dir.mkdir(parents=True, exist_ok=True)

    zip_path = extract_dir / "upload.zip"
    zip_path.write_bytes(file_bytes)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if name.startswith("/") or ".." in Path(name).parts:
                    shutil.rmtree(extract_dir, ignore_errors=True)
                    return None, f"Unsafe path in zip: {name}"
            zf.extractall(extract_dir)
    except zipfile.BadZipFile:
        shutil.rmtree(extract_dir, ignore_errors=True)
        return None, "File is not a valid ZIP archive"

    db_file = _find_db_file(extract_dir)
    if db_file is None:
        shutil.rmtree(extract_dir, ignore_errors=True)
        return None, (
            "No database file found in zip. Include a file named "
            "'database.sqlite' (or .db/.sqlite3/.sql)."
        )

    db_ext = db_file.suffix.lower()
    db_type = "sqlite" if db_ext in SQLITE_EXTENSIONS else "sql_dump"
    session = UploadSession(session_id, db_type)
    session.extract_dir = extract_dir

    db_bytes = db_file.read_bytes()
    if db_type == "sqlite":
        session.engine = _materialize_sqlite(session, db_bytes)
    else:
        session.engine = _materialize_sql_dump(session, db_bytes)

    examples = None
    if load_examples:
        examples_path = extract_dir / EXAMPLES_FILENAME
        if examples_path.exists():
            examples = _parse_examples(examples_path)
        else:
            logger.warning("load_examples requested but %s not found", EXAMPLES_FILENAME)

    return _finalize(session, examples=examples)


def _finalize(session: UploadSession, examples):
    """Run limit checks, enrich, train, register the session."""
    if not _within_limits(session):
        cleanup_session(session.session_id)
        return None, (
            f"Database exceeds limits: max {MAX_TABLES} tables, "
            f"max {MAX_COLUMNS_PER_TABLE} columns per table"
        )
    session.vanna_instance = _enrich_and_train(session, examples)
    _active_sessions[session.session_id] = session
    return session, None


# ============================================================
# Validation
# ============================================================

def _validate_upload(file_bytes: bytes, filename: str):
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        return f"File too large: {size_mb:.1f} MB (max {MAX_FILE_SIZE_MB} MB)"
    ext = Path(filename).suffix.lower()
    allowed = DB_EXTENSIONS | {".zip"}
    if ext not in allowed:
        return f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(allowed))}"
    return None


def _find_db_file(extract_dir: Path):
    """Locate the database file inside the extracted zip."""
    for candidate in DB_FILE_CANDIDATES:
        p = extract_dir / candidate
        if p.exists():
            return p
    db_files = [
        p for p in extract_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in DB_EXTENSIONS
    ]
    if len(db_files) == 1:
        return db_files[0]
    return None


def _parse_examples(path: Path):
    """Parse examples.jsonl into a list of {'question','sql'} dicts."""
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("examples.jsonl line %d is not valid JSON, skipped", line_no)
                continue
            q = obj.get("question")
            s = obj.get("sql")
            if isinstance(q, str) and isinstance(s, str) and q.strip() and s.strip():
                examples.append({"question": q.strip(), "sql": s.strip()})
                if len(examples) >= MAX_EXAMPLES:
                    break
            else:
                logger.warning("examples.jsonl line %d missing question/sql, skipped", line_no)
    return examples


def _is_sql_safe(statement: str) -> bool:
    for pattern in BLOCKED_SQL_PATTERNS:
        if re.search(pattern, statement, re.IGNORECASE):
            return False
    return True


def _within_limits(session: UploadSession) -> bool:
    with session.engine.connect() as conn:
        if session.db_type == "sqlite":
            tables = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )).fetchall()
        else:
            tables = conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = :schema
            """), {"schema": session.schema_name}).fetchall()

        session.table_count = len(tables)
        if session.table_count > MAX_TABLES:
            return False

        max_cols = 0
        for (table_name,) in tables:
            if session.db_type == "sqlite":
                cols = conn.execute(text(f"PRAGMA table_info('{table_name}')")).fetchall()
            else:
                cols = conn.execute(text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = :table
                """), {"schema": session.schema_name, "table": table_name}).fetchall()
            max_cols = max(max_cols, len(cols))
            session.column_count += len(cols)

        return max_cols <= MAX_COLUMNS_PER_TABLE


# ============================================================
# Materialization
# ============================================================

def _materialize_sqlite(session: UploadSession, db_bytes: bytes) -> Engine:
    TEMP_DIR_BASE.mkdir(parents=True, exist_ok=True)
    sqlite_path = TEMP_DIR_BASE / f"{session.session_id}.db"
    sqlite_path.write_bytes(db_bytes)
    session.sqlite_path = sqlite_path
    try:
        with sqlite3.connect(str(sqlite_path)) as conn:
            conn.execute("SELECT name FROM sqlite_master LIMIT 1")
    except sqlite3.DatabaseError:
        raise ValueError("File is not a valid SQLite database")
    return create_engine(f"sqlite:///{sqlite_path}")


def _materialize_sql_dump(session: UploadSession, db_bytes: bytes) -> Engine:
    sql_text = db_bytes.decode("utf-8", errors="replace")
    pg_engine = create_engine(DATABASE_URL)
    with pg_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{session.schema_name}"'))
    statements = _split_sql_statements(sql_text)
    with pg_engine.connect() as conn:
        conn.execute(text(f'SET search_path TO "{session.schema_name}"'))
        for stmt in statements:
            stmt = stmt.strip()
            if not stmt or stmt.startswith("--"):
                continue
            if not _is_sql_safe(stmt):
                continue
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()
    return pg_engine


def _split_sql_statements(sql_text: str):
    sql_text = re.sub(r"--[^\n]*", "", sql_text)
    sql_text = re.sub(r"/\*.*?\*/", "", sql_text, flags=re.DOTALL)
    return [s for s in sql_text.split(";") if s.strip()]


# ============================================================
# Enrichment + training (mirrors train_vanna_if_needed)
# ============================================================

def _enrich_and_train(session: UploadSession, examples):
    from vanna.openai import OpenAI_Chat
    from vanna.chromadb import ChromaDB_VectorStore
    from enrichment.metadata_extractor import MetadataExtractor
    from enrichment.fk_inference import FKInference

    engine = session.engine
    schema = session.schema_name if session.db_type == "sql_dump" else "main"
    dialect = session.dialect

    upload_url = (
        f"sqlite:///{session.sqlite_path}"
        if session.db_type == "sqlite" else DATABASE_URL
    )

    chroma_dir = TEMP_DIR_BASE / f"chroma_{session.session_id}"
    chroma_dir.mkdir(parents=True, exist_ok=True)

    class UploadVanna(ChromaDB_VectorStore, OpenAI_Chat):
        def __init__(self):
            ChromaDB_VectorStore.__init__(
                self, config={"persist_directory": str(chroma_dir)}
            )
            OpenAI_Chat.__init__(
                self, config={"api_key": OPENAI_API_KEY, "model": "gpt-4o-mini"}
            )

    vn = UploadVanna()

    _train_ddl_generic(vn, engine, session, schema)

    try:
        extractor = MetadataExtractor(
            source_url=upload_url, target_url=DATABASE_URL,
            source_engine=engine, target_engine=create_engine(DATABASE_URL),
        )
        for doc in extractor.format_for_vanna(schema):
            vn.train(documentation=doc)
    except Exception as e:
        logger.warning("Upload metadata enrichment failed: %s", e)

    try:
        fk = FKInference(
            source_url=upload_url, target_url=DATABASE_URL, dialect=dialect,
            source_engine=engine, target_engine=create_engine(DATABASE_URL),
        )
        for doc in fk.format_for_vanna(schema):
            vn.train(documentation=doc)
    except Exception as e:
        logger.warning("Upload FK inference failed: %s", e)

    if examples:
        for ex in examples:
            try:
                vn.train(question=ex["question"], sql=ex["sql"])
                session.example_count += 1
            except Exception as e:
                logger.warning("Failed to train example %r: %s", ex.get("question"), e)
        logger.info("Trained %d user-supplied examples", session.example_count)

    vn.connect_to_engine = engine
    return vn


def _train_ddl_generic(vn, engine: Engine, session: UploadSession, schema: str):
    with engine.connect() as conn:
        if session.db_type == "sqlite":
            rows = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
            )).fetchall()
            for (ddl,) in rows:
                if ddl:
                    vn.train(ddl=ddl)
        else:
            tables = conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = :schema
            """), {"schema": schema}).fetchall()
            for (table_name,) in tables:
                cols = conn.execute(text("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = :table
                    ORDER BY ordinal_position
                """), {"schema": schema, "table": table_name}).fetchall()
                lines = [f'CREATE TABLE "{schema}"."{table_name}" (']
                for name, dtype, nullable in cols:
                    null_str = "" if nullable == "YES" else " NOT NULL"
                    lines.append(f"    {name} {dtype}{null_str},")
                lines[-1] = lines[-1].rstrip(",")
                lines.append(");")
                vn.train(ddl="\n".join(lines))


# ============================================================
# Cleanup
# ============================================================

def cleanup_session(session_id: str) -> None:
    session = _active_sessions.pop(session_id, None)
    if session is None:
        for d in (TEMP_DIR_BASE / f"zip_{session_id}",
                  TEMP_DIR_BASE / f"chroma_{session_id}"):
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
        return

    if session.sqlite_path and session.sqlite_path.exists():
        try:
            session.sqlite_path.unlink()
        except OSError:
            pass

    for d in (session.extract_dir, TEMP_DIR_BASE / f"chroma_{session.session_id}"):
        if d and Path(d).exists():
            shutil.rmtree(d, ignore_errors=True)

    if session.db_type == "sql_dump":
        try:
            engine = create_engine(DATABASE_URL)
            with engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{session.schema_name}" CASCADE'))
        except Exception:
            pass


def cleanup_expired_sessions() -> int:
    expired = [sid for sid, s in _active_sessions.items() if s.is_expired()]
    for sid in expired:
        cleanup_session(sid)
    return len(expired)
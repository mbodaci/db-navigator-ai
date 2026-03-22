"""Initialize the MS SQL Server bank database.

SQL Server containers don't have a docker-entrypoint-initdb.d mechanism
like PostgreSQL, so this script handles first-time setup:
  1. Creates the 'dbnavigator' database if it doesn't exist
  2. Runs 01_create_bank_schema_mssql.sql
  3. Runs 02_seed_bank_data_mssql.sql

Usage:
    python scripts/init_mssql.py

    # Or with custom connection:
    python scripts/init_mssql.py "mssql+pyodbc://sa:DbNav2026!@localhost:1433/master?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"

Run this once after 'docker compose up -d', before using the app.
"""

import sys
import time
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError


SCRIPTS_DIR = Path(__file__).parent
DEFAULT_SA_URL = (
    "mssql+pyodbc://sa:DbNav2026!@localhost:1433/master"
    "?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
)
DB_NAME = "dbnavigator"


def wait_for_mssql(url: str, retries: int = 30, delay: float = 2.0) -> None:
    """Wait until SQL Server is accepting connections."""
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print(f"SQL Server ready (attempt {attempt})")
            engine.dispose()
            return
        except OperationalError:
            print(f"Waiting for SQL Server... (attempt {attempt}/{retries})")
            time.sleep(delay)
    engine.dispose()
    raise RuntimeError(f"SQL Server not ready after {retries} attempts")


def create_database(sa_url: str) -> None:
    """Create the dbnavigator database if it doesn't exist."""
    engine = create_engine(sa_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(text(
            f"SELECT DB_ID('{DB_NAME}')"
        )).scalar()
        if exists is None:
            conn.execute(text(f"CREATE DATABASE [{DB_NAME}]"))
            print(f"Created database '{DB_NAME}'")
        else:
            print(f"Database '{DB_NAME}' already exists")
    engine.dispose()


def run_sql_file(engine, filepath: Path) -> None:
    """Execute a .sql file against the engine.

    Splits on 'GO' statements (T-SQL batch separator).
    """
    if not filepath.exists():
        print(f"WARNING: {filepath} not found, skipping")
        return

    content = filepath.read_text(encoding="utf-8")

    # Split on GO (must be on its own line, case-insensitive)
    import re
    batches = re.split(r'^\s*GO\s*$', content, flags=re.MULTILINE | re.IGNORECASE)

    with engine.begin() as conn:
        for i, batch in enumerate(batches):
            batch = batch.strip()
            if not batch:
                continue
            try:
                conn.execute(text(batch))
            except Exception as e:
                print(f"  Batch {i+1} error: {e}")
                # Continue with remaining batches (some may be IF NOT EXISTS
                # checks that are expected to hit existing objects)

    print(f"Executed: {filepath.name}")


def main():
    sa_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SA_URL

    print("=== DB-Navigator AI: MS SQL Server Initialization ===")
    print()

    # 1. Wait for SQL Server
    wait_for_mssql(sa_url)

    # 2. Create database
    create_database(sa_url)

    # 3. Connect to the new database and run scripts
    db_url = sa_url.replace("/master", f"/{DB_NAME}")
    engine = create_engine(db_url)

    schema_file = SCRIPTS_DIR / "01_create_bank_schema_mssql.sql"
    seed_file = SCRIPTS_DIR / "02_seed_bank_data_mssql.sql"

    print()
    print("Running schema creation...")
    run_sql_file(engine, schema_file)

    print("Running seed data...")
    run_sql_file(engine, seed_file)

    engine.dispose()

    print()
    print("=== Initialization complete ===")
    print(f"Bank database ready at: mssql://localhost:1433/{DB_NAME}")


if __name__ == "__main__":
    main()

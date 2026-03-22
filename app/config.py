"""Configuration for DB-Navigator AI.

Dual-database architecture:
  - SOURCE: MS SQL Server (the undocumented bank database, read-only)
  - TARGET: PostgreSQL (app metadata, embeddings, query logs, benchmark)
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Source database (MS SQL Server - the bank DB you're enriching)
# ---------------------------------------------------------------------------
# Connection string format for pyodbc:
#   mssql+pyodbc://user:password@server/database?driver=ODBC+Driver+17+for+SQL+Server
# Connection string format for pymssql:
#   mssql+pymssql://user:password@server/database
SOURCE_DATABASE_URL = os.getenv(
    "SOURCE_DATABASE_URL",
    "mssql+pyodbc://sa:YourPassword@localhost/bankdb?driver=ODBC+Driver+17+for+SQL+Server"
)
BANK_SCHEMA = os.getenv("BANK_SCHEMA", "bank")

# ---------------------------------------------------------------------------
# Target database (PostgreSQL - app metadata, pgvector, logs)
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://dbnavigator:dbnavigator_dev@localhost:5432/dbnavigator"
)

# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # openai, anthropic, google
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Model selection per provider
LLM_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-20241022",
    "google": "gemini-2.0-flash",
}

# ---------------------------------------------------------------------------
# Embedding model (local, free)
# ---------------------------------------------------------------------------
EMBEDDING_MODEL = "all-mpnet-base-v2"
EMBEDDING_DIM = 768

# ---------------------------------------------------------------------------
# RAG settings
# ---------------------------------------------------------------------------
RAG_TOP_K = 10  # number of items to retrieve per collection
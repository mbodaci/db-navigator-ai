"""FastAPI service layer for DB-Navigator AI.

Wraps the natural-language-to-SQL engine behind a small HTTP API:

    GET  /health    liveness, readiness, and the active feature defaults
    POST /ask       answer a question (optional per-request correction flags)
    POST /correct   repair a specific SQL statement
    POST /feedback  log an accepted answer and optionally add it to training
    GET  /schema    tables, columns, and inferred relationships

The service runs inside the Streamlit container's environment (working
directory ``/app``), so imports of project modules use no ``app.`` prefix.
"""

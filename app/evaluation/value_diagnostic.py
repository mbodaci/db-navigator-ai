"""Diagnostic: surface the actual value_mapping failures from the benchmark log.

Reads the queries the benchmark already logged to ``public.query_log`` and prints
the distinct questions that were scored as ``value_mapping`` errors, together with
one example of the SQL the model generated and whether it executed - with NO LLM
calls. The point is to design value-retrieval against the errors that actually
occur, rather than against an assumed shape.

What we are looking for in the output, per failing question:
  (a) literal lookup  - the question names a value ("London", "Visa", "Gold") and
      the model put the wrong / a missing literal in the WHERE clause. A value
      index over the distinct column values can fix this.
  (b) code mapping    - the question uses a label ("active", "closed") but the
      column stores a code ('A', 'C'). String matching alone cannot bridge this;
      it needs a lookup table or an explicit synonym map.

Run from the repo root:
    python -m app.evaluation.value_diagnostic
"""
from collections import OrderedDict

from sqlalchemy import create_engine, text

try:
    from app.config import DATABASE_URL
except ImportError:  # when run from inside app/
    from config import DATABASE_URL


def _one_line(sql: str, limit: int = 240) -> str:
    flat = " ".join((sql or "").split())
    return flat if len(flat) <= limit else flat[:limit] + " ..."


def main():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT question, generated_sql, executed_ok, execution_error, feedback_note "
            "FROM public.query_log "
            "WHERE feedback_note LIKE '%error_type=value_mapping%' "
            "AND generated_sql IS NOT NULL "
            "ORDER BY id"
        )).fetchall()

    if not rows:
        print("No value_mapping errors found in public.query_log.")
        return

    # One entry per distinct question (the same question fails the same way across runs).
    by_q = OrderedDict()
    for question, sql, ok, err, _note in rows:
        if question not in by_q:
            by_q[question] = (sql, ok, err)

    print(f"value_mapping error rows logged : {len(rows)}")
    print(f"distinct failing questions       : {len(by_q)}\n")

    for i, (question, (sql, ok, err)) in enumerate(by_q.items(), 1):
        status = "ok" if ok else f"ERROR: {_one_line(err, 120)}"
        print(f"{i:2d}. Q: {question}")
        print(f"    SQL : {_one_line(sql)}")
        print(f"    exec: {status}\n")


if __name__ == "__main__":
    main()

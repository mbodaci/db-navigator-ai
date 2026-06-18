"""Diagnostic: re-run the join validator over previously generated queries.

Reads the queries the benchmark already logged to ``public.query_log`` and reports
what the join validator does with each - with NO LLM calls. It answers the
question the zero-fire join-path run raised: is the validator silent because the
model produces no disconnected-table errors, or because the failing queries fall
outside what it can detect?

Two reports:
  1. The validator's category over every logged query.
  2. The category specifically for queries that were scored as missing_join or
     wrong_join errors - the decisive test. If those land in 'connected', the
     referenced tables ARE joined and the error is a missing table or a wrong
     join column, neither of which disconnection analysis can catch.

Run from the repo root:
    python -m app.evaluation.join_diagnostic
"""
from collections import Counter

from sqlalchemy import create_engine, text

try:
    from app.config import DATABASE_URL
except ImportError:  # when run from inside app/
    from config import DATABASE_URL

from app.enrichment.fk_inference import SYNTHETIC_DB_GROUND_TRUTH
from app.pipeline.join_paths import JoinPathEngine
from app.pipeline.join_validator import JoinValidator


def main():
    validator = JoinValidator(JoinPathEngine(SYNTHETIC_DB_GROUND_TRUTH), dialect="tsql")
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT generated_sql, feedback_note FROM public.query_log "
            "WHERE generated_sql IS NOT NULL"
        )).fetchall()

    if not rows:
        print("No logged queries found in public.query_log.")
        return

    overall = Counter(validator.diagnose(sql) for sql, _ in rows)
    print(f"Validator category over {len(rows)} logged queries:")
    for cat, n in overall.most_common():
        print(f"  {cat:22s}: {n}")

    join_errs = [
        sql for sql, note in rows
        if note and ("error_type=missing_join" in note or "error_type=wrong_join" in note)
    ]
    print(f"\nQueries logged with a missing_join or wrong_join error: {len(join_errs)}")
    if join_errs:
        jcat = Counter(validator.diagnose(sql) for sql in join_errs)
        for cat, n in jcat.most_common():
            print(f"  validator says '{cat}': {n}")
        print("\nReading:")
        print("  connected            -> tables ARE joined; error is a missing table or a")
        print("                          wrong join column (disconnection analysis can't see it)")
        print("  missing_join_flagged -> the validator WOULD have caught it (re-check needed)")
        print("  not_analyzable       -> outside parse scope (subquery, etc.)")


if __name__ == "__main__":
    main()

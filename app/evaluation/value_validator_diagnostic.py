"""Diagnostic: re-run the value validator over previously generated queries.

Parallels join_diagnostic. Builds the value-domain index exactly as the benchmark
does (enriched_columns cardinalities + distinct values pulled from the source DB),
prints which columns it covers, then runs the validator over every generated query
in public.query_log with NO LLM calls. It answers why the --value-check run fired
only once: is it because the model's value_mapping errors are out-of-domain literals
the validator should catch (so a coverage / wiring gap), or because they are
wrong-but-valid codes, missing predicates, or date conventions that no domain check
can see?

Run from the repo root:
    python -m app.evaluation.value_validator_diagnostic
"""
from collections import Counter

from sqlalchemy import create_engine, text

try:
    from app.config import DATABASE_URL, SOURCE_DATABASE_URL
except ImportError:  # when run from inside app/
    from config import DATABASE_URL, SOURCE_DATABASE_URL

from app.pipeline.value_index import (
    build_value_index, make_source_fetch, SYNTHETIC_DB_VALUE_LABELS,
)
from app.pipeline.value_validator import ValueValidator

SCHEMA = "bank"


def build_index(target, source):
    with target.connect() as conn:
        rows = conn.execute(text("""
            SELECT table_name, column_name, distinct_count
            FROM public.enriched_columns
            WHERE schema_name = :schema AND distinct_count IS NOT NULL
        """), {"schema": SCHEMA}).fetchall()
    columns = [(r[0], r[1], r[2]) for r in rows]
    return build_value_index(columns, make_source_fetch(source, SCHEMA),
                             label_map=SYNTHETIC_DB_VALUE_LABELS)


def main():
    target = create_engine(DATABASE_URL)
    source = create_engine(SOURCE_DATABASE_URL)

    index = build_index(target, source)
    print(f"Value-domain index covers {len(index)} columns:")
    for t, c in sorted(index.columns()):
        dom = index.get(t, c)
        sample = ", ".join(sorted(dom.values, key=str.casefold)[:8]) if dom else ""
        print(f"  {t}.{c}  ({len(dom.values) if dom else 0} values: {sample})")
    print()

    validator = ValueValidator(index, dialect="tsql")
    with target.connect() as conn:
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
        print(f"  {cat:24s}: {n}")

    vm = [sql for sql, note in rows if note and "error_type=value_mapping" in note]
    print(f"\nQueries logged with a value_mapping error: {len(vm)}")
    if vm:
        vcat = Counter(validator.diagnose(sql) for sql in vm)
        for cat, n in vcat.most_common():
            print(f"  validator says '{cat}': {n}")

        print("\nDistinct predicates the validator flags as out-of-domain:")
        seen = set()
        for sql in vm:
            r = validator.validate(sql)
            if not r.ok:
                for v in r.violations:
                    key = (v.table, v.column, str(v.value).casefold())
                    if key not in seen:
                        seen.add(key)
                        print(f"  {v.table}.{v.column} = '{v.value}'  -> suggest {v.suggestion}")
        if not seen:
            print("  (none -- the validator catches none of the logged value_mapping errors)")

    print("\nReading:")
    print("  out_of_domain_flagged -> validator WOULD fire (catchable value error)")
    print("  all_valid             -> literals exist in their column; wrong-but-valid code")
    print("  no_literal_predicate  -> no indexed col=literal to check (missing predicate / dates)")
    print("  not_analyzable        -> parse or scope miss")


if __name__ == "__main__":
    main()

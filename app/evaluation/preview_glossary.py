"""Preview the code glossary exactly as the benchmark builds it.

Prints the rendered code dictionary so its accuracy can be checked before running a
benchmark with --code-glossary: confirm the auto-pulled lookup names (account /
transaction type, loan product) are right, and that the hand-authored descriptions
(especially branch/employee stat_cd 1=active/0=inactive) match the real data.

Run from the repo root:
    python -m app.evaluation.preview_glossary
"""
from sqlalchemy import create_engine, text

try:
    from app.config import DATABASE_URL, SOURCE_DATABASE_URL
except ImportError:  # when run from inside app/
    from config import DATABASE_URL, SOURCE_DATABASE_URL

from app.pipeline.code_glossary import build_code_glossary, make_lookup_fetch

SCHEMA = "bank"


def main():
    target = create_engine(DATABASE_URL)
    source = create_engine(SOURCE_DATABASE_URL)

    with target.connect() as conn:
        rows = conn.execute(text(
            "SELECT table_name, column_name FROM public.enriched_columns "
            "WHERE schema_name = :schema"
        ), {"schema": SCHEMA}).fetchall()
    present = {(r[0].casefold(), r[1].casefold()) for r in rows}

    glossary = build_code_glossary(make_lookup_fetch(source, SCHEMA), only_columns=present)
    block = glossary.render()

    print(block)
    print()
    print(f"[{len(glossary)} columns, {len(block)} characters injected per question]")


if __name__ == "__main__":
    main()

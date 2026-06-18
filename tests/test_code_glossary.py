"""Unit tests for the code glossary.

No database: the lookup-table fetch is replaced with a dict-backed fake, so building,
merging, the name-column heuristic, column filtering, and rendering are checked
deterministically. The key assertion is that the per-table stat_cd split survives
into the rendered text (account 'OPEN' vs loan 'ACTIVE' vs branch '1').

Run directly (``python tests/test_code_glossary.py``) or under pytest.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from pipeline.code_glossary import (
    CodeGlossary,
    build_code_glossary,
    _pick_name_col,
    CODE_DESCRIPTIONS,
    LOOKUP_SOURCES,
)


FAKE_LOOKUP = {
    ("tbl_acct_tp", "acct_tp_cd"): {
        "CUR_PF": "Personal current account",
        "DEP_TRM": "Term deposit",
        "SAV": "Savings account",
    },
    ("tbl_txn_tp", "txn_tp_cd"): {"DEP_CSH": "Cash deposit", "FEE": "Fee"},
    ("tbl_loan_prod", "prod_cd"): {"MORT_PRM": "Prime mortgage", "AUTO_NEW": "New auto loan"},
}


def fake_fetch(lookup_table, code_col, name_col_guess=None):
    return FAKE_LOOKUP.get((lookup_table, code_col), {})


# --------------------------------------------------------------------------- #
# Name-column heuristic
# --------------------------------------------------------------------------- #
def test_pick_name_col_prefers_nm_suffix():
    cols = ["acct_tp_cd", "acct_tp_nm", "created_dt"]
    assert _pick_name_col(cols, "acct_tp_cd") == "acct_tp_nm"


def test_pick_name_col_falls_back_to_text_column():
    cols = ["prod_cd", "description", "prod_id"]
    assert _pick_name_col(cols, "prod_cd") == "description"


def test_pick_name_col_skips_ids_and_dates():
    cols = ["code", "code_id", "code_dt"]
    assert _pick_name_col(cols, "code") is None


# --------------------------------------------------------------------------- #
# CodeGlossary structure + render
# --------------------------------------------------------------------------- #
def test_add_merges_codes():
    g = CodeGlossary()
    g.add("tbl_acct", "stat_cd", {"OPEN": "open"})
    g.add("tbl_acct", "stat_cd", {"FROZEN": "frozen"})
    assert g.get("tbl_acct", "stat_cd") == {"OPEN": "open", "FROZEN": "frozen"}


def test_render_groups_by_table():
    g = CodeGlossary()
    g.add("tbl_acct", "stat_cd", {"OPEN": "active / open account"})
    g.add("tbl_acct", "acct_tp_cd", {"SAV": "savings"})
    g.add("tbl_loan", "stat_cd", {"ACTIVE": "active / outstanding loan"})
    text = g.render()
    assert "tbl_acct:" in text
    assert "tbl_loan:" in text
    # account stat appears once under its table header
    assert text.count("tbl_acct:") == 1
    assert "stat_cd: OPEN = active / open account" in text


def test_render_empty_is_empty_string():
    assert CodeGlossary().render() == ""


# --------------------------------------------------------------------------- #
# build_code_glossary
# --------------------------------------------------------------------------- #
def test_build_merges_lookup_and_hand():
    g = build_code_glossary(fake_fetch)
    # lookup-backed
    assert g.get("tbl_acct", "acct_tp_cd")["DEP_TRM"] == "Term deposit"
    # hand-authored
    assert g.get("tbl_cust", "cust_tp")["PF"].startswith("individual")


def test_build_preserves_per_table_stat_cd_split():
    g = build_code_glossary(fake_fetch)
    text = g.render()
    # the whole point: same concept, different code per table
    assert "OPEN = active / open account" in text       # accounts
    assert "ACTIVE = active / outstanding loan" in text  # loans
    assert "1 = active / operating branch" in text       # branches
    # and they are distinct columns in the output
    assert g.get("tbl_acct", "stat_cd") != g.get("tbl_loan", "stat_cd")


def test_build_only_columns_filter():
    keep = {("tbl_cust", "cust_tp"), ("tbl_acct", "acct_tp_cd")}
    g = build_code_glossary(fake_fetch, only_columns=keep)
    assert g.get("tbl_cust", "cust_tp") is not None
    assert g.get("tbl_acct", "acct_tp_cd") is not None
    assert g.get("tbl_loan", "stat_cd") is None   # filtered out


def test_build_skips_lookup_with_no_names():
    # A fetch that returns nothing must not create an empty entry.
    g = build_code_glossary(lambda *a, **k: {})
    assert g.get("tbl_acct", "acct_tp_cd") is None
    # hand entries still present
    assert g.get("tbl_cust", "cust_tp") is not None


def test_descriptions_cover_the_diagnostic_culprits():
    # Sanity: the columns the value diagnostic flagged are described.
    for key in [("tbl_acct", "stat_cd"), ("tbl_cust", "cust_tp"),
                ("tbl_cust", "stat_cd"), ("tbl_txn", "dr_cr_ind")]:
        assert key in CODE_DESCRIPTIONS
    assert ("tbl_acct", "acct_tp_cd") in LOOKUP_SOURCES


# --------------------------------------------------------------------------- #
# Minimal runner
# --------------------------------------------------------------------------- #
def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed, failed = 0, 0
    for fn in tests:
        try:
            fn()
            passed += 1
            print(f"PASS {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)

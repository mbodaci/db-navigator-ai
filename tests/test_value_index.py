"""Unit tests for the value-domain index.

No database, LLM, or network: the live distinct-value fetch is replaced with a
dict-backed fake, so column selection, domain membership, the label-driven repair
suggestion, and the build wiring are all checked deterministically. The scenarios
mirror the real value_mapping failures from the benchmark log (the model emitting
'ACTIVE' for an account whose status is 'OPEN', 'individual' for cust_tp 'PF',
etc.), including the per-table point that the same column name has different
domains in different tables.

Run directly (``python tests/test_value_index.py``) or under pytest.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from pipeline.value_index import (
    ColumnDomain,
    ValueDomainIndex,
    build_value_index,
    looks_like_code_column,
    SYNTHETIC_DB_VALUE_LABELS,
    _norm_ident,
)


# --------------------------------------------------------------------------- #
# Fakes / fixtures
# --------------------------------------------------------------------------- #
# Distinct values exactly as the source DB would return them (codes the model
# does NOT guess correctly). Note stat_cd differs per table.
FAKE_DISTINCT = {
    ("tbl_acct", "stat_cd"): ["OPEN", "CLOSED", "DORMANT"],
    ("tbl_loan", "stat_cd"): ["ACTIVE", "CLOSED", "DEFAULT"],
    ("tbl_card", "stat_cd"): ["ACTIVE", "BLOCKED", "EXPIRED"],
    ("tbl_cust", "cust_tp"): ["PF", "PJ"],
    ("tbl_acct", "acct_tp_cd"): ["SAV", "CHK", "DEP"],
    ("tbl_txn", "dr_cr_ind"): ["D", "C"],
    ("tbl_cust", "cust_nm"): ["Ion", "Maria", "Acme SRL"],   # not a code column
    ("tbl_acct", "acct_no"): ["1001", "1002", "1003"],       # id-like
}


def fake_fetch(table, column):
    return FAKE_DISTINCT.get((table, column), [])


# columns metadata: (table, column, distinct_count)
FAKE_COLUMNS = [
    ("tbl_acct", "stat_cd", 3),
    ("tbl_loan", "stat_cd", 3),
    ("tbl_card", "stat_cd", 3),
    ("tbl_cust", "cust_tp", 2),
    ("tbl_acct", "acct_tp_cd", 3),
    ("tbl_txn", "dr_cr_ind", 2),
    ("tbl_cust", "cust_nm", 50000),     # high cardinality -> excluded
    ("tbl_acct", "acct_no", 100000),    # id-like high cardinality -> excluded
    ("tbl_acct", "cur_bal", 90000),     # not a code column -> excluded
]


def make_index():
    return build_value_index(FAKE_COLUMNS, fake_fetch, label_map=SYNTHETIC_DB_VALUE_LABELS)


# --------------------------------------------------------------------------- #
# Identifier + column-name heuristics
# --------------------------------------------------------------------------- #
def test_norm_ident_strips_schema_and_quoting():
    assert _norm_ident("[bank].[tbl_acct]") == "tbl_acct"
    assert _norm_ident("a.STAT_CD") == "stat_cd"
    assert _norm_ident('"tbl_cust"') == "tbl_cust"
    assert _norm_ident("tbl_br") == "tbl_br"


def test_looks_like_code_column():
    assert looks_like_code_column("stat_cd")
    assert looks_like_code_column("cust_tp")
    assert looks_like_code_column("dr_cr_ind")
    assert looks_like_code_column("acct_tp_cd")
    assert looks_like_code_column("status")
    assert not looks_like_code_column("cust_nm")
    assert not looks_like_code_column("acct_no")
    assert not looks_like_code_column("cur_bal")


# --------------------------------------------------------------------------- #
# ColumnDomain
# --------------------------------------------------------------------------- #
def test_domain_membership_is_case_insensitive():
    dom = ColumnDomain("tbl_acct", "stat_cd", {"OPEN", "CLOSED"})
    assert dom.is_valid("OPEN")
    assert dom.is_valid("open")
    assert dom.is_valid("  Open ")
    assert not dom.is_valid("ACTIVE")


def test_suggest_via_exact_label():
    dom = ColumnDomain("tbl_cust", "cust_tp", {"PF", "PJ"},
                       labels={"PF": ["individual", "personal"], "PJ": ["corporate", "company"]})
    assert dom.suggest("individual") == "PF"
    assert dom.suggest("Corporate") == "PJ"


def test_suggest_via_substring_label():
    dom = ColumnDomain("tbl_cust", "cust_tp", {"PF", "PJ"},
                       labels={"PJ": ["corporate"]})
    assert dom.suggest("corporate customers") == "PJ"


def test_suggest_via_close_string_match():
    dom = ColumnDomain("tbl_acct", "acct_tp_cd", {"SAVINGS", "CHECKING"})
    assert dom.suggest("saving") == "SAVINGS"
    assert dom.suggest("Savings") == "SAVINGS"


def test_suggest_returns_none_when_unmappable():
    dom = ColumnDomain("tbl_acct", "acct_tp_cd", {"SAV", "CHK", "DEP"})
    assert dom.suggest("DEPOSIT") is None


def test_describe_includes_values_and_labels():
    dom = ColumnDomain("tbl_cust", "cust_tp", {"PF", "PJ"},
                       labels={"PF": ["individual"], "PJ": ["corporate"]})
    text = dom.describe()
    assert "'PF'" in text and "'PJ'" in text
    assert "meaning" in text and "individual" in text


# --------------------------------------------------------------------------- #
# ValueDomainIndex
# --------------------------------------------------------------------------- #
def test_index_skips_unindexed_columns():
    idx = make_index()
    assert idx.has_column("tbl_cust", "cust_nm") is False
    assert idx.is_valid("tbl_cust", "cust_nm", "literally anything") is True
    assert idx.suggest("tbl_cust", "cust_nm", "anything") is None


def test_index_lookup_is_alias_and_schema_tolerant():
    idx = make_index()
    assert idx.has_column("[bank].[tbl_acct]", "STAT_CD")
    assert idx.is_valid("tbl_acct", "stat_cd", "open")


# --------------------------------------------------------------------------- #
# build_value_index: selection + population + the real per-table scenarios
# --------------------------------------------------------------------------- #
def test_build_selects_only_low_card_code_columns():
    idx = make_index()
    assert idx.has_column("tbl_acct", "stat_cd")
    assert idx.has_column("tbl_cust", "cust_tp")
    assert idx.has_column("tbl_txn", "dr_cr_ind")
    assert not idx.has_column("tbl_cust", "cust_nm")
    assert not idx.has_column("tbl_acct", "acct_no")
    assert not idx.has_column("tbl_acct", "cur_bal")


def test_build_include_and_exclude_overrides():
    idx = build_value_index(
        FAKE_COLUMNS, fake_fetch,
        label_map=SYNTHETIC_DB_VALUE_LABELS,
        include=[("tbl_cust", "cust_nm")],
        exclude=[("tbl_txn", "dr_cr_ind")],
    )
    assert idx.has_column("tbl_cust", "cust_nm")        # forced in
    assert not idx.has_column("tbl_txn", "dr_cr_ind")   # forced out


def test_account_active_is_flagged_and_repaired_to_open():
    # The headline case (#11): model wrote stat_cd='ACTIVE' for an account.
    idx = make_index()
    assert idx.is_valid("tbl_acct", "stat_cd", "ACTIVE") is False
    assert idx.suggest("tbl_acct", "stat_cd", "ACTIVE") == "OPEN"


def test_individual_and_corporate_map_to_pf_pj():
    # Cases #7 and #8.
    idx = make_index()
    assert idx.is_valid("tbl_cust", "cust_tp", "individual") is False
    assert idx.suggest("tbl_cust", "cust_tp", "individual") == "PF"
    assert idx.is_valid("tbl_cust", "cust_tp", "corporate") is False
    assert idx.suggest("tbl_cust", "cust_tp", "corporate") == "PJ"


def test_per_table_domains_do_not_collide():
    # stat_cd='ACTIVE' is WRONG for an account but RIGHT for a loan or card.
    idx = make_index()
    assert idx.is_valid("tbl_acct", "stat_cd", "ACTIVE") is False
    assert idx.is_valid("tbl_loan", "stat_cd", "ACTIVE") is True
    assert idx.is_valid("tbl_card", "stat_cd", "ACTIVE") is True


def test_integer_literal_against_string_domain_is_flagged():
    # Case #15: model wrote b.stat_cd = 1 against a string-coded column.
    idx = make_index()
    assert idx.is_valid("tbl_acct", "stat_cd", 1) is False


# --------------------------------------------------------------------------- #
# Minimal runner (so the file works without pytest)
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

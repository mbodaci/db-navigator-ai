"""Unit tests for the value-domain validator.

No database, LLM, or network: an index is built from a dict-backed fake fetch, then
real generated-SQL strings (taken from the benchmark's value_mapping failures) are
validated. Covers qualified and unqualified column resolution, per-table domains,
IN lists, numeric literals, CASE predicates, the conservative skips (ambiguous
unqualified columns, sub-queries, join equalities), and the repair hint.

Run directly (``python tests/test_value_validator.py``) or under pytest.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from pipeline.value_index import build_value_index, SYNTHETIC_DB_VALUE_LABELS
from pipeline.value_validator import ValueValidator


FAKE_DISTINCT = {
    ("tbl_acct", "stat_cd"): ["OPEN", "CLOSED", "DORMANT"],
    ("tbl_loan", "stat_cd"): ["ACTIVE", "CLOSED", "DEFAULT"],
    ("tbl_card", "stat_cd"): ["ACTIVE", "BLOCKED", "EXPIRED"],
    ("tbl_cust", "cust_tp"): ["PF", "PJ"],
    ("tbl_acct", "acct_tp_cd"): ["SAV", "CHK", "DEP"],
    ("tbl_txn", "dr_cr_ind"): ["D", "C"],
}
FAKE_COLUMNS = [
    ("tbl_acct", "stat_cd", 3),
    ("tbl_loan", "stat_cd", 3),
    ("tbl_card", "stat_cd", 3),
    ("tbl_cust", "cust_tp", 2),
    ("tbl_acct", "acct_tp_cd", 3),
    ("tbl_txn", "dr_cr_ind", 2),
]


def _validator():
    idx = build_value_index(FAKE_COLUMNS, lambda t, c: FAKE_DISTINCT.get((t, c), []),
                            label_map=SYNTHETIC_DB_VALUE_LABELS)
    return ValueValidator(idx, dialect="tsql")


V = _validator()


# --------------------------------------------------------------------------- #
# The fixable cases from the diagnostic
# --------------------------------------------------------------------------- #
def test_unqualified_single_table_account_active():
    r = V.validate("SELECT * FROM bank.tbl_acct WHERE stat_cd = 'ACTIVE'")
    assert r.ok is False
    assert len(r.violations) == 1
    v = r.violations[0]
    assert (v.table, v.column, v.value, v.suggestion) == ("tbl_acct", "stat_cd", "ACTIVE", "OPEN")


def test_qualified_account_active_with_join():
    sql = ("SELECT a.acct_no FROM bank.tbl_acct a "
           "JOIN bank.tbl_acct_tp at ON a.acct_tp_cd = at.acct_tp_cd "
           "WHERE a.stat_cd = 'ACTIVE'")
    r = V.validate(sql)
    assert r.ok is False
    assert [(v.table, v.column, v.suggestion) for v in r.violations] == [("tbl_acct", "stat_cd", "OPEN")]


def test_individual_maps_to_pf():
    r = V.validate("SELECT cust_no FROM bank.tbl_cust WHERE cust_tp = 'individual'")
    assert r.ok is False
    assert r.violations[0].suggestion == "PF"


def test_corporate_maps_to_pj():
    r = V.validate("SELECT * FROM bank.tbl_cust WHERE cust_tp = 'CORP'")
    # 'CORP' is out of domain; substring label match on 'corp' inside 'corporate'
    assert r.ok is False
    assert r.violations[0].suggestion == "PJ"


def test_numeric_literal_flagged():
    r = V.validate("SELECT * FROM bank.tbl_acct WHERE stat_cd = 1")
    assert r.ok is False
    assert r.violations[0].value == "1"


def test_in_list_flags_only_bad_member():
    r = V.validate("SELECT * FROM bank.tbl_acct WHERE stat_cd IN ('OPEN', 'ACTIVE')")
    assert r.ok is False
    assert len(r.violations) == 1
    assert r.violations[0].value == "ACTIVE"


def test_case_predicate_with_bad_value_flagged():
    sql = ("SELECT SUM(CASE WHEN dr_cr_ind = 'X' THEN txn_amt ELSE 0 END) "
           "FROM bank.tbl_txn")
    r = V.validate(sql)
    assert r.ok is False
    assert r.violations[0].column == "dr_cr_ind"


# --------------------------------------------------------------------------- #
# Must NOT fire (correctness of conservatism)
# --------------------------------------------------------------------------- #
def test_valid_value_not_flagged():
    assert V.validate("SELECT * FROM bank.tbl_acct WHERE stat_cd = 'OPEN'").ok is True


def test_loan_active_is_valid_per_table():
    # Same literal that is wrong for an account is right for a loan.
    assert V.validate("SELECT * FROM bank.tbl_loan WHERE stat_cd = 'ACTIVE'").ok is True


def test_qualified_resolution_picks_right_table():
    # Two tables both have stat_cd; the qualified alias decides which domain applies.
    sql = ("SELECT * FROM bank.tbl_acct a JOIN bank.tbl_loan l ON a.acct_no = l.acct_no "
           "WHERE l.stat_cd = 'ACTIVE'")
    assert V.validate(sql).ok is True   # 'ACTIVE' valid for the loan
    sql2 = sql.replace("l.stat_cd = 'ACTIVE'", "a.stat_cd = 'ACTIVE'")
    assert V.validate(sql2).ok is False  # 'ACTIVE' invalid for the account


def test_ambiguous_unqualified_column_is_skipped():
    # Unqualified stat_cd with two tables that both have it -> ambiguous -> skip.
    sql = ("SELECT * FROM bank.tbl_acct a JOIN bank.tbl_loan l ON a.acct_no = l.acct_no "
           "WHERE stat_cd = 'ACTIVE'")
    assert V.validate(sql).ok is True


def test_case_predicate_with_valid_value_not_flagged():
    sql = ("SELECT SUM(CASE WHEN dr_cr_ind = 'D' THEN txn_amt ELSE 0 END) "
           "FROM bank.tbl_txn")
    assert V.validate(sql).ok is True


def test_join_equality_not_treated_as_literal():
    sql = ("SELECT * FROM bank.tbl_acct a JOIN bank.tbl_cust c ON a.cust_no = c.cust_no")
    assert V.validate(sql).ok is True


def test_unindexed_column_skipped():
    assert V.validate("SELECT * FROM bank.tbl_acct WHERE cur_bal = 999").ok is True


def test_subquery_does_not_crash_and_no_false_positive():
    sql = ("SELECT l.loan_no FROM bank.tbl_loan l LEFT JOIN "
           "(SELECT acct_no, SUM(txn_amt) AS s FROM bank.tbl_txn GROUP BY acct_no) c "
           "ON l.acct_no = c.acct_no WHERE c.s < l.outst_princ")
    assert V.validate(sql).ok is True


def test_derived_table_plus_real_predicate_still_checks():
    # A real base table coexisting with a derived table: the real predicate is checked.
    sql = ("SELECT a.acct_no FROM bank.tbl_acct a JOIN "
           "(SELECT cust_no FROM bank.tbl_cust) c ON a.cust_no = c.cust_no "
           "WHERE a.stat_cd = 'ACTIVE'")
    r = V.validate(sql)
    assert r.ok is False
    assert r.violations[0].table == "tbl_acct"


def test_empty_and_garbage_are_ok():
    assert V.validate("").ok is True
    assert V.validate("   ").ok is True
    assert V.validate("not sql at all ;;;").ok is True
    assert V.validate(None).ok is True


def test_hint_names_domain_and_suggestion():
    r = V.validate("SELECT * FROM bank.tbl_acct WHERE stat_cd = 'ACTIVE'")
    assert "OPEN" in r.hint
    assert "Use 'OPEN'" in r.hint
    assert "stat_cd" in r.hint


# --------------------------------------------------------------------------- #
# diagnose()
# --------------------------------------------------------------------------- #
def test_diagnose_categories():
    assert V.diagnose("SELECT * FROM bank.tbl_acct WHERE stat_cd = 'ACTIVE'") == "out_of_domain_flagged"
    assert V.diagnose("SELECT * FROM bank.tbl_acct WHERE stat_cd = 'OPEN'") == "all_valid"
    assert V.diagnose("SELECT * FROM bank.tbl_acct WHERE cur_bal = 5") == "no_literal_predicate"
    assert V.diagnose("not sql ;;;") == "not_analyzable"


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

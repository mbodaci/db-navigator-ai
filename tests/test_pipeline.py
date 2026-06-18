"""Unit tests for the accuracy pipeline.

These run without any database, LLM, or network: Vanna and the SQL executor are
replaced with fakes so the control logic of the self-correction loop and the
engine can be checked deterministically. The tests document the contract the
loop is expected to honour:

    * a query that executes is returned unchanged (no repair, baseline behaviour);
    * a failing query is repaired and re-executed;
    * repairs are capped, and a no-op or non-SQL repair stops the loop;
    * with the correction flag off (max_iters=0) behaviour matches the baseline;
    * the /correct seed path repairs without regenerating;
    * the SQL post-processing and result-signature helpers behave as specified.

Run directly (``python tests/test_pipeline.py``) or under pytest.
"""
import datetime
import decimal
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from pipeline.engine import FeatureNotEnabledError, NLToSQLEngine
from pipeline.flags import PipelineConfig
from pipeline.join_paths import JoinPathEngine, JoinStep
from pipeline.join_validator import JoinValidator, ValidationResult
from pipeline.value_index import build_value_index
from pipeline.value_validator import ValueValidator
from pipeline.self_correction import SelfCorrectionLoop
from pipeline.voting import SelfConsistencyVoter
from pipeline import sql_utils


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeVanna:
    """Programmable stand-in for a Vanna client.

    ``gen`` is the queue of initial generations; ``repairs`` is the queue of
    repair responses (what ``submit_prompt`` returns, which ``extract_sql`` then
    passes through). Calls and the temperature seen at each ``submit_prompt`` are
    recorded so tests can assert on them.
    """

    def __init__(self, gen=None, repairs=None, ddl=None, docs=None):
        self.temperature = 0.7
        self._gen = list(gen or [])
        self._repairs = list(repairs or [])
        self.ddl = ddl if ddl is not None else ["CREATE TABLE [bank].[tbl_cust] ([cust_no] INT)"]
        self.docs = docs if docs is not None else ["stat_cd ACTIVE means active customer"]
        self.generate_calls = []
        self.submit_temperatures = []
        self.gen_temperatures = []
        self.extract_inputs = []

    def generate_sql(self, question, **kwargs):
        self.generate_calls.append(question)
        self.gen_temperatures.append(self.temperature)
        return self._gen.pop(0)

    def get_related_ddl(self, question):
        return self.ddl

    def get_related_documentation(self, question):
        return self.docs

    def system_message(self, content):
        return {"role": "system", "content": content}

    def user_message(self, content):
        return {"role": "user", "content": content}

    def submit_prompt(self, prompt, **kwargs):
        self.submit_temperatures.append(self.temperature)
        return self._repairs.pop(0)

    def extract_sql(self, response):
        self.extract_inputs.append(response)
        return response


class RecordingExecutor:
    """Executor returning queued ``(df, err)`` results and counting calls."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def __call__(self, sql):
        self.calls.append(sql)
        if not self._results:
            raise AssertionError("executor called more often than expected")
        return self._results.pop(0)


class SqlExecutor:
    """Executor that returns a fixed ``(df, err)`` for each SQL string.

    Lets voting tests control which candidates land in which result group.
    """

    def __init__(self, mapping, default=(None, "unknown sql")):
        self._mapping = mapping
        self._default = default
        self.calls = []

    def __call__(self, sql):
        self.calls.append(sql)
        return self._mapping.get(sql, self._default)


def passthrough(sql):
    return sql.strip() if isinstance(sql, str) else sql


def df_rows(n=2):
    return pd.DataFrame({"a": list(range(n))})


def make_loop(vn, executor, **kwargs):
    params = dict(dialect="mssql", postprocess_fn=passthrough)
    params.update(kwargs)
    return SelfCorrectionLoop(vn=vn, execute_fn=executor, **params)


# --------------------------------------------------------------------------- #
# Self-correction loop
# --------------------------------------------------------------------------- #
def test_success_first_try_no_repair():
    vn = FakeVanna(gen=["SELECT TOP 1 * FROM [bank].[tbl_cust]"])
    ex = RecordingExecutor([(df_rows(), None)])
    res = make_loop(vn, ex, max_iters=2).run("show one customer")

    assert res.executed_ok is True
    assert res.iterations == 0
    assert res.was_corrected is False
    assert len(res.steps) == 1 and res.steps[0].action == "initial"
    assert vn.submit_temperatures == []  # no repair attempted
    assert len(ex.calls) == 1


def test_repair_then_success():
    vn = FakeVanna(
        gen=["SELECT bad FROM t"],
        repairs=["SELECT good FROM [bank].[tbl_cust]"],
    )
    ex = RecordingExecutor([(None, "Invalid column name 'bad'"), (df_rows(), None)])
    res = make_loop(vn, ex, max_iters=2).run("q")

    assert res.executed_ok is True
    assert res.iterations == 1
    assert res.was_corrected is True
    assert res.final_sql == "SELECT good FROM [bank].[tbl_cust]"
    actions = [s.action for s in res.steps]
    assert actions == ["initial", "repair"]


def test_caps_iterations():
    vn = FakeVanna(
        gen=["SELECT v0 FROM t"],
        repairs=["SELECT v1 FROM t", "SELECT v2 FROM t", "SELECT v3 FROM t"],
    )
    err = (None, "boom")
    ex = RecordingExecutor([err, err, err])  # initial + 2 repairs all fail
    res = make_loop(vn, ex, max_iters=2).run("q")

    assert res.executed_ok is False
    assert res.iterations == 2
    assert sum(1 for s in res.steps if s.action == "repair") == 2
    assert len(vn.submit_temperatures) == 2  # exactly max_iters repair calls


def test_repair_noop_stops():
    vn = FakeVanna(gen=["SELECT x FROM t"], repairs=["SELECT x FROM t"])
    ex = RecordingExecutor([(None, "boom")])
    res = make_loop(vn, ex, max_iters=3).run("q")

    assert res.iterations == 1
    assert res.was_corrected is False
    assert res.steps[-1].action == "repair_noop"
    assert res.executed_ok is False


def test_max_iters_zero_matches_baseline():
    vn = FakeVanna(gen=["SELECT x FROM t"])
    ex = RecordingExecutor([(None, "boom")])
    res = make_loop(vn, ex, max_iters=0).run("q")

    assert res.iterations == 0
    assert res.executed_ok is False
    assert len(res.steps) == 1 and res.steps[0].action == "initial"
    assert vn.generate_calls == ["q"]
    assert vn.submit_temperatures == []  # never tried to repair


def test_seed_path_skips_generation():
    vn = FakeVanna(repairs=["SELECT good FROM t"])
    ex = RecordingExecutor([(df_rows(), None)])  # only the repair executes
    res = make_loop(vn, ex, max_iters=1).run(
        "q", seed_sql="SELECT bad FROM t", seed_error="boom"
    )

    assert vn.generate_calls == []  # no regeneration on the seed path
    assert res.steps[0].action == "seed"
    assert res.executed_ok is True
    assert res.iterations == 1


def test_retry_on_empty_enabled():
    vn = FakeVanna(gen=["SELECT a FROM t"], repairs=["SELECT b FROM t"])
    ex = RecordingExecutor([(pd.DataFrame(), None), (df_rows(), None)])
    res = make_loop(vn, ex, max_iters=2, retry_on_empty=True).run("q")

    assert res.iterations == 1
    assert res.was_corrected is True
    assert res.executed_ok is True


def test_retry_on_empty_disabled():
    vn = FakeVanna(gen=["SELECT a FROM t"])
    ex = RecordingExecutor([(pd.DataFrame(), None)])
    res = make_loop(vn, ex, max_iters=2, retry_on_empty=False).run("q")

    assert res.iterations == 0
    assert res.executed_ok is True  # empty but valid
    assert vn.submit_temperatures == []


def test_non_sql_generation_is_not_executed():
    vn = FakeVanna(gen=["I cannot answer that question."])
    ex = RecordingExecutor([])  # must never be called
    res = make_loop(vn, ex, max_iters=0).run("q")

    assert res.executed_ok is False
    assert res.error is not None
    assert len(ex.calls) == 0


def test_repair_temperature_pinned_then_restored():
    vn = FakeVanna(gen=["SELECT bad FROM t"], repairs=["SELECT good FROM t"])
    ex = RecordingExecutor([(None, "boom"), (df_rows(), None)])
    make_loop(vn, ex, max_iters=1, repair_temperature=0.0).run("q")

    assert vn.submit_temperatures == [0.0]  # repair ran at the pinned temperature
    assert vn.temperature == 0.7  # original value restored afterwards


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
def make_engine(vn, executor, config, join_validator=None, value_validator=None, code_glossary=None):
    return NLToSQLEngine(
        vn=vn,
        execute_fn=executor,
        postprocess_fn=passthrough,
        dialect="mssql",
        config=config,
        join_validator=join_validator,
        value_validator=value_validator,
        code_glossary=code_glossary,
    )


def test_engine_baseline_mode():
    vn = FakeVanna(gen=["SELECT good FROM t"])
    ex = RecordingExecutor([(df_rows(), None)])
    res = make_engine(vn, ex, PipelineConfig()).answer("q")

    assert res.mode == "baseline"
    assert res.correction_iterations == 0
    assert vn.submit_temperatures == []


def test_engine_self_correction_mode():
    vn = FakeVanna(gen=["SELECT bad FROM t"], repairs=["SELECT good FROM t"])
    ex = RecordingExecutor([(None, "boom"), (df_rows(), None)])
    cfg = PipelineConfig(self_correction=True, correction_max_iters=2)
    res = make_engine(vn, ex, cfg).answer("q")

    assert res.mode == "self_correction"
    assert res.was_corrected is True
    assert res.sql == "SELECT good FROM t"


def test_engine_voting_mode():
    df_a = pd.DataFrame({"x": [1]})
    df_b = pd.DataFrame({"x": [2]})
    vn = FakeVanna(gen=["SELECT a FROM t", "SELECT a FROM t", "SELECT b FROM t"])
    ex = SqlExecutor({"SELECT a FROM t": (df_a, None), "SELECT b FROM t": (df_b, None)})
    cfg = PipelineConfig(voting=True, voting_n=3, voting_temperature=0.7)
    res = make_engine(vn, ex, cfg).answer("q")

    assert res.mode == "voting"
    assert res.sql == "SELECT a FROM t"  # 2 of 3 candidates agreed on this result
    assert res.executed_ok is True
    assert res.confidence == 2 / 3


def test_engine_correct_uses_seed():
    vn = FakeVanna(repairs=["SELECT good FROM t"])
    ex = RecordingExecutor([(df_rows(), None)])
    res = make_engine(vn, ex, PipelineConfig()).correct(
        "q", sql="SELECT bad FROM t", error="boom", max_iters=1
    )

    assert res.mode == "self_correction"
    assert vn.generate_calls == []
    assert res.executed_ok is True


def test_engine_join_paths_repairs_missing_join():
    # First generation cross-joins txn and cust; the validator flags it and the
    # engine re-prompts, the second generation supplies the FK path.
    good = ("SELECT * FROM tbl_txn JOIN tbl_acct ON tbl_txn.acct_no = tbl_acct.acct_no "
            "JOIN tbl_cust ON tbl_acct.cust_no = tbl_cust.cust_no")
    vn = FakeVanna(gen=["SELECT * FROM tbl_txn, tbl_cust", good])
    ex = SqlExecutor({good: (pd.DataFrame({"x": [1]}), None)})
    validator = JoinValidator(JoinPathEngine(BANK_FKS))
    cfg = PipelineConfig(join_paths=True)
    res = make_engine(vn, ex, cfg, join_validator=validator).answer("q")

    assert res.mode == "join_paths"
    assert res.was_corrected is True
    assert res.correction_iterations == 1
    assert res.sql == good
    assert res.executed_ok is True


def test_engine_join_paths_accepts_valid_join():
    sql = "SELECT * FROM tbl_txn JOIN tbl_acct ON tbl_txn.acct_no = tbl_acct.acct_no"
    vn = FakeVanna(gen=[sql])
    ex = SqlExecutor({sql: (pd.DataFrame({"x": [1]}), None)})
    validator = JoinValidator(JoinPathEngine(BANK_FKS))
    res = make_engine(vn, ex, PipelineConfig(join_paths=True), join_validator=validator).answer("q")

    assert res.mode == "join_paths"
    assert res.was_corrected is False
    assert res.sql == sql  # no re-prompt: only one generation consumed


def test_engine_join_paths_without_validator_falls_back():
    vn = FakeVanna(gen=["SELECT good FROM t"])
    ex = RecordingExecutor([(df_rows(), None)])
    res = make_engine(vn, ex, PipelineConfig(join_paths=True)).answer("q")
    assert res.mode == "baseline"  # flag on but no validator injected -> baseline path


def _value_validator():
    idx = build_value_index(
        [("tbl_acct", "stat_cd", 2)],
        lambda t, c: ["OPEN", "CLOSED"],
        label_map={("tbl_acct", "stat_cd"): {"OPEN": ["active", "open"]}},
    )
    return ValueValidator(idx, dialect="tsql")


def test_engine_value_check_repairs_bad_value():
    # First generation filters on a non-existent code; the validator flags it and
    # the engine re-prompts, the second generation uses the real code.
    bad = "SELECT * FROM bank.tbl_acct WHERE stat_cd = 'ACTIVE'"
    good = "SELECT * FROM bank.tbl_acct WHERE stat_cd = 'OPEN'"
    vn = FakeVanna(gen=[bad, good])
    ex = SqlExecutor({good: (pd.DataFrame({"x": [1]}), None)})
    cfg = PipelineConfig(value_check=True)
    res = make_engine(vn, ex, cfg, value_validator=_value_validator()).answer("q")

    assert res.mode == "value_check"
    assert res.was_corrected is True
    assert res.correction_iterations == 1
    assert res.sql == good
    assert res.executed_ok is True


def test_engine_value_check_accepts_valid_value():
    sql = "SELECT * FROM bank.tbl_acct WHERE stat_cd = 'OPEN'"
    vn = FakeVanna(gen=[sql])
    ex = SqlExecutor({sql: (pd.DataFrame({"x": [1]}), None)})
    res = make_engine(vn, ex, PipelineConfig(value_check=True),
                      value_validator=_value_validator()).answer("q")

    assert res.mode == "value_check"
    assert res.was_corrected is False
    assert res.sql == sql  # no re-prompt: only one generation consumed


def test_engine_value_check_without_validator_falls_back():
    vn = FakeVanna(gen=["SELECT good FROM t"])
    ex = RecordingExecutor([(df_rows(), None)])
    res = make_engine(vn, ex, PipelineConfig(value_check=True)).answer("q")
    assert res.mode == "baseline"  # flag on but no validator injected -> baseline path


def test_engine_code_glossary_injects_before_question():
    glossary = "Code dictionary:\n  tbl_acct:\n    stat_cd: OPEN = active account"
    vn = FakeVanna(gen=["SELECT * FROM bank.tbl_acct WHERE stat_cd = 'OPEN'"])
    ex = SqlExecutor({"SELECT * FROM bank.tbl_acct WHERE stat_cd = 'OPEN'": (pd.DataFrame({"x": [1]}), None)})
    res = make_engine(vn, ex, PipelineConfig(code_glossary=True), code_glossary=glossary).answer("how many active accounts")

    assert res.mode == "code_glossary"
    assert res.was_corrected is False
    # the glossary text was prepended to the question the model actually saw
    assert glossary in vn.generate_calls[0]
    assert "how many active accounts" in vn.generate_calls[0]
    assert len(vn.generate_calls) == 1  # single generation, no re-prompt


def test_engine_code_glossary_without_text_falls_back():
    vn = FakeVanna(gen=["SELECT good FROM t"])
    ex = RecordingExecutor([(df_rows(), None)])
    res = make_engine(vn, ex, PipelineConfig(code_glossary=True)).answer("q")
    assert res.mode == "baseline"  # flag on but no glossary string injected -> baseline path


# --------------------------------------------------------------------------- #
# Self-consistency voting
# --------------------------------------------------------------------------- #
DF_A = pd.DataFrame({"x": [1]})
DF_B = pd.DataFrame({"x": [2]})
DF_EMPTY = pd.DataFrame()


def make_voter(vn, executor, n, temperature=0.7):
    return SelfConsistencyVoter(
        vn=vn, execute_fn=executor, postprocess_fn=passthrough, n=n, temperature=temperature
    )


def test_voting_majority_wins():
    vn = FakeVanna(gen=["SELECT a FROM t", "SELECT a FROM t", "SELECT a FROM t",
                        "SELECT b FROM t", "SELECT b FROM t"])
    ex = SqlExecutor({"SELECT a FROM t": (DF_A, None), "SELECT b FROM t": (DF_B, None)})
    res = make_voter(vn, ex, n=5).run("q")

    assert res.final_sql == "SELECT a FROM t"
    assert res.winning_votes == 3
    assert res.n_successful == 5
    assert res.confidence == 3 / 5
    assert res.executed_ok is True


def test_voting_tie_breaks_toward_nonempty():
    # 2 empty vs 2 non-empty: a tie that must resolve to the non-empty result.
    vn = FakeVanna(gen=["SELECT empty FROM t", "SELECT empty FROM t",
                        "SELECT rows FROM t", "SELECT rows FROM t"])
    ex = SqlExecutor({"SELECT empty FROM t": (DF_EMPTY, None),
                      "SELECT rows FROM t": (DF_A, None)})
    res = make_voter(vn, ex, n=4).run("q")

    assert res.final_sql == "SELECT rows FROM t"
    assert len(res.df) == 1
    assert res.winning_votes == 2


def test_voting_all_candidates_fail():
    vn = FakeVanna(gen=["SELECT x FROM t", "SELECT y FROM t", "SELECT z FROM t"])
    ex = SqlExecutor({}, default=(None, "Invalid column"))
    res = make_voter(vn, ex, n=3).run("q")

    assert res.executed_ok is False
    assert res.n_successful == 0
    assert res.confidence == 0.0
    assert res.error is not None


def test_voting_unanimous_confidence():
    vn = FakeVanna(gen=["SELECT a FROM t", "SELECT a FROM t", "SELECT a FROM t"])
    ex = SqlExecutor({"SELECT a FROM t": (DF_A, None)})
    res = make_voter(vn, ex, n=3).run("q")

    assert res.confidence == 1.0
    assert res.winning_votes == 3


def test_voting_samples_at_voting_temperature():
    vn = FakeVanna(gen=["SELECT a FROM t", "SELECT a FROM t"])
    ex = SqlExecutor({"SELECT a FROM t": (DF_A, None)})
    make_voter(vn, ex, n=2, temperature=0.8).run("q")

    assert vn.gen_temperatures == [0.8, 0.8]  # all samples drawn at the voting temperature
    assert vn.temperature == 0.7  # restored afterwards


def test_voting_non_sql_candidate_excluded():
    # One candidate is prose; it must not win or crash the vote.
    vn = FakeVanna(gen=["I cannot answer", "SELECT a FROM t", "SELECT a FROM t"])
    ex = SqlExecutor({"SELECT a FROM t": (DF_A, None)})
    res = make_voter(vn, ex, n=3).run("q")

    assert res.final_sql == "SELECT a FROM t"
    assert res.n_successful == 2
    assert res.winning_votes == 2


# --------------------------------------------------------------------------- #
# Join-path engine
# --------------------------------------------------------------------------- #
# A realistic subset of the bank FK graph (src_table, src_col, tgt_table, tgt_col).
BANK_FKS = [
    ("tbl_emp", "br_cd", "tbl_br", "br_cd"),
    ("tbl_emp", "mgr_emp_no", "tbl_emp", "emp_no"),       # self-reference
    ("tbl_cust", "br_cd", "tbl_br", "br_cd"),
    ("tbl_acct", "cust_no", "tbl_cust", "cust_no"),
    ("tbl_acct", "br_cd", "tbl_br", "br_cd"),
    ("tbl_txn", "acct_no", "tbl_acct", "acct_no"),
    ("tbl_loan", "cust_no", "tbl_cust", "cust_no"),
    ("tbl_loan", "disb_acct_no", "tbl_acct", "acct_no"),  # two FKs to the same table
    ("tbl_loan", "repay_acct_no", "tbl_acct", "acct_no"),
]

# Two disconnected components: {txn, acct} and {card, cust}.
DISCONNECTED_FKS = [
    ("tbl_txn", "acct_no", "tbl_acct", "acct_no"),
    ("tbl_card", "cust_no", "tbl_cust", "cust_no"),
]


def test_join_direct_neighbor():
    steps = JoinPathEngine(BANK_FKS).path("tbl_txn", "tbl_acct")
    assert len(steps) == 1
    s = steps[0]
    assert (s.left_table, s.left_col, s.right_table, s.right_col) == \
        ("tbl_txn", "acct_no", "tbl_acct", "acct_no")


def test_join_two_hops():
    steps = JoinPathEngine(BANK_FKS).path("tbl_txn", "tbl_cust")
    assert [(s.left_table, s.left_col, s.right_table, s.right_col) for s in steps] == [
        ("tbl_txn", "acct_no", "tbl_acct", "acct_no"),
        ("tbl_acct", "cust_no", "tbl_cust", "cust_no"),
    ]


def test_join_same_table_is_empty():
    assert JoinPathEngine(BANK_FKS).path("tbl_acct", "tbl_acct") == []


def test_join_unknown_table_is_none():
    assert JoinPathEngine(BANK_FKS).path("tbl_txn", "tbl_does_not_exist") is None


def test_join_disconnected_is_none():
    assert JoinPathEngine(DISCONNECTED_FKS).path("tbl_txn", "tbl_cust") is None


def test_join_multi_edge_keeps_alternatives():
    steps = JoinPathEngine(BANK_FKS).path("tbl_loan", "tbl_acct")
    assert len(steps) == 1
    s = steps[0]
    assert (s.left_col, s.right_col) == ("disb_acct_no", "acct_no")
    assert s.alternatives == [("repay_acct_no", "acct_no")]


def test_join_self_reference():
    eng = JoinPathEngine(BANK_FKS)
    assert eng.path("tbl_emp", "tbl_emp") == []  # self-ref is not a path edge
    sj = eng.self_joins("tbl_emp")
    assert [(s.left_table, s.left_col, s.right_table, s.right_col) for s in sj] == [
        ("tbl_emp", "mgr_emp_no", "tbl_emp", "emp_no"),
    ]


def test_join_connect_three_tables():
    steps = JoinPathEngine(BANK_FKS).connect(["tbl_txn", "tbl_cust", "tbl_br"])
    tables = {s.left_table for s in steps} | {s.right_table for s in steps}
    assert tables == {"tbl_txn", "tbl_acct", "tbl_cust", "tbl_br"}
    assert len(steps) == 3  # four tables connect with three joins (a tree)


def test_join_to_sql():
    eng = JoinPathEngine(BANK_FKS)
    sql = eng.to_sql("tbl_txn", eng.path("tbl_txn", "tbl_cust"))
    assert sql == (
        "tbl_txn JOIN tbl_acct ON tbl_txn.acct_no = tbl_acct.acct_no "
        "JOIN tbl_cust ON tbl_acct.cust_no = tbl_cust.cust_no"
    )


# --------------------------------------------------------------------------- #
# Join validation (sqlglot)
# --------------------------------------------------------------------------- #
def make_validator():
    return JoinValidator(JoinPathEngine(BANK_FKS))


def test_validator_ok_two_table_join():
    sql = "SELECT * FROM tbl_txn JOIN tbl_acct ON tbl_txn.acct_no = tbl_acct.acct_no"
    assert make_validator().validate(sql).ok is True


def test_validator_ok_with_aliases():
    sql = "SELECT * FROM tbl_txn t JOIN tbl_acct a ON t.acct_no = a.acct_no"
    assert make_validator().validate(sql).ok is True


def test_validator_ok_single_table():
    assert make_validator().validate("SELECT * FROM tbl_acct").ok is True


def test_validator_ok_where_style_join():
    # Old-style join expressed in WHERE must not be flagged.
    sql = "SELECT * FROM tbl_txn t, tbl_acct a WHERE t.acct_no = a.acct_no"
    assert make_validator().validate(sql).ok is True


def test_validator_detects_missing_join():
    res = make_validator().validate("SELECT * FROM tbl_txn, tbl_cust")
    assert res.ok is False
    assert res.reason == "missing_join"
    assert res.tables == ["tbl_cust", "tbl_txn"]


def test_validator_hint_names_intermediate_table():
    res = make_validator().validate("SELECT * FROM tbl_txn, tbl_cust")
    assert res.hint is not None
    assert "tbl_acct" in res.hint  # the FK path routes transactions to customers via accounts


def test_validator_unparseable_is_ok():
    # Cannot analyse -> must not flag (silence beats a false positive).
    assert make_validator().validate("not valid sql ;;;").ok is True


# --------------------------------------------------------------------------- #
# SQL helpers
# --------------------------------------------------------------------------- #
def test_fix_tsql_converts_trailing_limit():
    assert sql_utils.fix_tsql_syntax("SELECT * FROM t LIMIT 5;") == "SELECT TOP 5 * FROM t"
    assert sql_utils.fix_tsql_syntax("SELECT a FROM t") == "SELECT a FROM t"


def test_fix_standard_converts_top():
    assert sql_utils.fix_standard_syntax("SELECT TOP 5 * FROM t") == "SELECT * FROM t LIMIT 5"


def test_clean_sql_strips_fences():
    assert sql_utils.clean_sql("```sql\nSELECT 1\n```") == "SELECT 1"
    assert sql_utils.clean_sql("SELECT 1;") == "SELECT 1"


def test_looks_like_sql():
    assert sql_utils.looks_like_sql("SELECT 1") is True
    assert sql_utils.looks_like_sql("WITH x AS (SELECT 1) SELECT * FROM x") is True
    assert sql_utils.looks_like_sql("I cannot answer") is False
    assert sql_utils.looks_like_sql(None) is False
    assert sql_utils.looks_like_sql("   ") is False


def test_result_signature_order_independent():
    df1 = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    df2 = pd.DataFrame({"a": [2, 1], "b": [4, 3]})  # rows reordered
    df3 = pd.DataFrame({"b": [3, 4], "a": [1, 2]})  # columns reordered
    s1 = sql_utils.result_signature(df1)
    assert s1 == sql_utils.result_signature(df2)
    assert s1 == sql_utils.result_signature(df3)
    assert sql_utils.result_signature(pd.DataFrame()) == "EMPTY"
    assert sql_utils.result_signature(None) is None


def test_df_to_records_json_safe():
    df = pd.DataFrame({
        "amt": [decimal.Decimal("10.5")],
        "when": [datetime.datetime(2025, 2, 1, 12, 0, 0)],
        "n": [float("nan")],
    })
    cols, rows, truncated = sql_utils.df_to_records(df, max_rows=200)
    assert cols == ["amt", "when", "n"]
    assert truncated is False
    assert isinstance(rows[0][0], float) and rows[0][0] == 10.5
    assert rows[0][1] == "2025-02-01T12:00:00"
    assert rows[0][2] is None


def test_df_to_records_truncation():
    df = pd.DataFrame({"a": [1, 2, 3]})
    cols, rows, truncated = sql_utils.df_to_records(df, max_rows=2)
    assert truncated is True
    assert len(rows) == 2


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
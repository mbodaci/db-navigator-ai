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
from pipeline.self_correction import SelfCorrectionLoop
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
        self.extract_inputs = []

    def generate_sql(self, question, **kwargs):
        self.generate_calls.append(question)
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
def make_engine(vn, executor, config):
    return NLToSQLEngine(
        vn=vn,
        execute_fn=executor,
        postprocess_fn=passthrough,
        dialect="mssql",
        config=config,
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


def test_engine_voting_rejected():
    vn = FakeVanna(gen=["SELECT good FROM t"])
    ex = RecordingExecutor([(df_rows(), None)])
    cfg = PipelineConfig(voting=True)
    raised = False
    try:
        make_engine(vn, ex, cfg).answer("q")
    except FeatureNotEnabledError:
        raised = True
    assert raised is True


def test_engine_correct_uses_seed():
    vn = FakeVanna(repairs=["SELECT good FROM t"])
    ex = RecordingExecutor([(df_rows(), None)])
    res = make_engine(vn, ex, PipelineConfig()).correct(
        "q", sql="SELECT bad FROM t", error="boom", max_iters=1
    )

    assert res.mode == "self_correction"
    assert vn.generate_calls == []
    assert res.executed_ok is True


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

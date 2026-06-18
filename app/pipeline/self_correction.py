"""Execution-guided self-correction loop.

This is one of the student-written control algorithms that wraps the LLM. The
LLM is a single replaceable component inside it: the loop generates SQL, executes
it, and when execution fails (or, optionally, returns a degenerate empty result)
it re-prompts the model with the failed query, the exact database error, and the
retrieved schema context, asking for a fix. It iterates up to a fixed cap, with
the first repair expected to yield most of the gain.

The class depends only on:
    * a Vanna-style LLM client exposing generate_sql / get_related_ddl /
      get_related_documentation / system_message / user_message / submit_prompt /
      extract_sql (and a settable ``temperature`` attribute),
    * an ``execute_fn(sql) -> (DataFrame|None, error_str|None)`` callable,
    * a ``postprocess_fn(sql) -> sql`` callable (dialect fix-ups).

All three are injected, so the same loop drives both the API and the benchmark.
With ``max_iters=0`` the loop performs exactly one generation and one execution
and returns, which reproduces the documented baseline generation path.
"""
import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import pandas as pd

from .sql_utils import looks_like_sql, row_count

_DIALECT_PROFILES = {
    "mssql": {
        "label": "Microsoft SQL Server (Transact-SQL)",
        "rules": (
            "Use Transact-SQL syntax. Use TOP n instead of LIMIT n. Quote identifiers "
            "with square brackets, for example [table].[column], and keep the schema "
            "qualifier shown in the DDL."
        ),
    },
    "postgresql": {
        "label": "PostgreSQL",
        "rules": "Use standard SQL. Use LIMIT n rather than TOP n. Quote identifiers with double quotes when needed.",
    },
    "sqlite": {
        "label": "SQLite",
        "rules": "Use standard SQL. Use LIMIT n rather than TOP n.",
    },
}

_GENERIC_PROFILE = {
    "label": "SQL",
    "rules": "Use standard SQL that is valid for the target database.",
}

_SYSTEM_TEMPLATE = (
    "You are an expert {label} engineer working with an undocumented banking database. "
    "A SQL query failed or produced an incorrect result when it was executed. Using the "
    "schema context, the failed query, and the exact database error, write a single corrected "
    "query that executes successfully and answers the question. {rules} Pay close attention to "
    "exact column names, the join keys implied by the relationship notes, and the documented "
    "codes for status, currency, and category values. Respond with the corrected SQL only: no "
    "commentary and no markdown fences."
)

_EMPTY_RESULT_NOTE = (
    "The query executed without error but returned zero rows, which appears incorrect for this "
    "question. Reconsider the filters, the value codes, and the joins."
)


@dataclass
class CorrectionStep:
    iteration: int
    sql: Optional[str]
    executed_ok: bool
    error: Optional[str]
    row_count: Optional[int]
    action: str


@dataclass
class CorrectionResult:
    question: str
    final_sql: Optional[str]
    df: Optional[pd.DataFrame]
    executed_ok: bool
    error: Optional[str]
    iterations: int
    steps: List[CorrectionStep] = field(default_factory=list)

    @property
    def was_corrected(self) -> bool:
        """True if at least one repair changed the query."""
        return any(s.action.startswith("repair") and s.action != "repair_noop" for s in self.steps)


class SelfCorrectionLoop:

    def __init__(
        self,
        vn,
        execute_fn: Callable[[str], Tuple[Optional[pd.DataFrame], Optional[str]]],
        postprocess_fn: Callable[[Optional[str]], Optional[str]],
        dialect: str = "mssql",
        max_iters: int = 2,
        retry_on_empty: bool = False,
        repair_temperature: float = 0.0,
        logger: Optional[logging.Logger] = None,
    ):
        self._vn = vn
        self._execute = execute_fn
        self._postprocess = postprocess_fn
        self._dialect = (dialect or "mssql").lower()
        self._max_iters = max(0, int(max_iters))
        self._retry_on_empty = retry_on_empty
        self._repair_temperature = repair_temperature
        self._log = logger or logging.getLogger(__name__)

    def run(
        self,
        question: str,
        seed_sql: Optional[str] = None,
        seed_error: Optional[str] = None,
    ) -> CorrectionResult:
        """Generate (or accept a seed), execute, and repair on failure.

        When ``seed_sql`` is given the initial generation is skipped and the loop
        starts from that query (used by the /correct endpoint). If ``seed_error``
        is also given, it is taken as the failing error without re-executing.
        """
        steps: List[CorrectionStep] = []

        if seed_sql is None:
            sql = self._generate_initial(question)
            action = "initial"
        else:
            sql = self._postprocess(seed_sql)
            action = "seed"

        if seed_sql is not None and seed_error is not None:
            df, err = None, seed_error
        else:
            df, err = self._execute_guarded(sql)
        steps.append(self._make_step(0, sql, err, df, action))

        iteration = 0
        while self._needs_fix(err, df) and iteration < self._max_iters:
            iteration += 1
            repaired = self._repair(question, sql, err, df)

            if not repaired or repaired.strip() == (sql or "").strip():
                steps.append(self._make_step(iteration, repaired or sql, err, df, "repair_noop"))
                self._log.info("self-correction: repair %d produced no change, stopping", iteration)
                break

            sql = repaired
            if not looks_like_sql(sql):
                err = "model response was not a SQL statement"
                df = None
                steps.append(self._make_step(iteration, sql, err, df, "repair_invalid"))
                break

            df, err = self._execute_guarded(sql)
            steps.append(self._make_step(iteration, sql, err, df, "repair"))
            if err is None:
                self._log.info("self-correction: repair %d fixed the query", iteration)

        executed_ok = err is None and looks_like_sql(sql)
        return CorrectionResult(
            question=question,
            final_sql=sql,
            df=df,
            executed_ok=executed_ok,
            error=err,
            iterations=iteration,
            steps=steps,
        )

    def _generate_initial(self, question: str) -> Optional[str]:
        raw = self._vn.generate_sql(question=question)
        return self._postprocess(raw)

    def _execute_guarded(self, sql: Optional[str]) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        if not looks_like_sql(sql):
            return None, "generation did not return a SQL statement"
        return self._execute(sql)

    def _needs_fix(self, err: Optional[str], df: Optional[pd.DataFrame]) -> bool:
        if err is not None:
            return True
        if self._retry_on_empty and df is not None and df.empty:
            return True
        return False

    def _repair(
        self,
        question: str,
        failed_sql: Optional[str],
        error: Optional[str],
        df: Optional[pd.DataFrame],
    ) -> Optional[str]:
        ddl_list = self._safe_retrieve(self._vn.get_related_ddl, question)
        doc_list = self._safe_retrieve(self._vn.get_related_documentation, question)
        error_text = error or _EMPTY_RESULT_NOTE
        user_message = self._build_user_message(question, ddl_list, doc_list, failed_sql, error_text)
        prompt = [
            self._vn.system_message(self._system_message()),
            self._vn.user_message(user_message),
        ]
        response = self._submit_low_temperature(prompt)
        return self._postprocess(self._vn.extract_sql(response))

    def _safe_retrieve(self, fn: Callable[[str], list], question: str) -> list:
        try:
            result = fn(question)
            return result if result else []
        except Exception as exc:
            self._log.warning("self-correction: retrieval failed (%s)", exc)
            return []

    def _submit_low_temperature(self, prompt) -> str:
        previous = getattr(self._vn, "temperature", None)
        try:
            if previous is not None:
                self._vn.temperature = self._repair_temperature
            return self._vn.submit_prompt(prompt)
        finally:
            if previous is not None:
                self._vn.temperature = previous

    def _system_message(self) -> str:
        profile = _DIALECT_PROFILES.get(self._dialect, _GENERIC_PROFILE)
        return _SYSTEM_TEMPLATE.format(label=profile["label"], rules=profile["rules"])

    @staticmethod
    def _build_user_message(
        question: str,
        ddl_list: list,
        doc_list: list,
        failed_sql: Optional[str],
        error_text: str,
    ) -> str:
        parts = []
        if ddl_list:
            parts.append("Schema (DDL):\n" + "\n\n".join(str(d) for d in ddl_list))
        if doc_list:
            parts.append(
                "Documentation and relationship notes:\n"
                + "\n".join(f"- {d}" for d in doc_list)
            )
        parts.append(f"Question:\n{question}")
        parts.append(f"Failed SQL:\n{failed_sql}")
        parts.append(f"Database error:\n{error_text}")
        parts.append("Corrected SQL:")
        return "\n\n".join(parts)

    @staticmethod
    def _make_step(
        iteration: int,
        sql: Optional[str],
        err: Optional[str],
        df: Optional[pd.DataFrame],
        action: str,
    ) -> CorrectionStep:
        return CorrectionStep(
            iteration=iteration,
            sql=sql,
            executed_ok=err is None,
            error=err,
            row_count=row_count(df),
            action=action,
        )

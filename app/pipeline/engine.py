"""Engine that turns a natural-language question into an executed SQL result.

The engine is the single entry point the API uses. It applies the configured
accuracy techniques on top of the LLM:

    * with the default config it runs the documented baseline path
      (generate -> post-process -> execute), via a correction loop capped at
      zero repairs, so results match Config F exactly;
    * with ``self_correction`` enabled it runs the execution-guided repair loop;
    * voting is a reserved seam: the config field exists, but enabling it raises
      until the voting module lands in the next step (kept off by default so the
      baseline is never affected).

Generation, execution, and SQL post-processing are injected, so the engine has
no knowledge of which database or dialect it is serving.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import pandas as pd

from .flags import PipelineConfig
from .join_validator import JoinValidator
from .self_correction import CorrectionResult, CorrectionStep, SelfCorrectionLoop
from .sql_utils import looks_like_sql, row_count
from .value_validator import ValueValidator
from .voting import SelfConsistencyVoter, VotingResult


class FeatureNotEnabledError(RuntimeError):
    """Raised when a requested technique is not implemented yet."""


@dataclass
class AskResult:
    question: str
    sql: Optional[str]
    executed_ok: bool
    error: Optional[str]
    df: Optional[pd.DataFrame]
    row_count: Optional[int]
    mode: str
    correction_iterations: int
    correction_steps: List[CorrectionStep] = field(default_factory=list)
    was_corrected: bool = False
    latency_ms: int = 0
    confidence: Optional[float] = None


class NLToSQLEngine:

    def __init__(
        self,
        vn,
        execute_fn: Callable[[str], Tuple[Optional[pd.DataFrame], Optional[str]]],
        postprocess_fn: Callable[[Optional[str]], Optional[str]],
        dialect: str = "mssql",
        config: Optional[PipelineConfig] = None,
        logger: Optional[logging.Logger] = None,
        join_validator: Optional[JoinValidator] = None,
        value_validator: Optional[ValueValidator] = None,
    ):
        self._vn = vn
        self._execute = execute_fn
        self._postprocess = postprocess_fn
        self._dialect = dialect
        self._config = config or PipelineConfig()
        self._log = logger or logging.getLogger(__name__)
        self._join_validator = join_validator
        self._value_validator = value_validator

    @property
    def config(self) -> PipelineConfig:
        return self._config

    def answer(self, question: str, config: Optional[PipelineConfig] = None) -> AskResult:
        cfg = config or self._config
        t0 = time.perf_counter()

        if cfg.voting:
            return self._answer_by_voting(question, cfg, t0)

        if cfg.join_paths and self._join_validator is not None:
            return self._answer_with_join_paths(question, cfg, t0)

        if cfg.value_check and self._value_validator is not None:
            return self._answer_with_value_check(question, cfg, t0)

        max_iters = cfg.correction_max_iters if cfg.self_correction else 0
        loop = self._build_loop(
            max_iters=max_iters,
            retry_on_empty=cfg.correction_retry_on_empty,
            repair_temperature=cfg.correction_temperature,
        )
        result = loop.run(question)
        mode = "self_correction" if cfg.self_correction else "baseline"
        return self._to_ask_result(result, mode, t0)

    def _answer_by_voting(self, question: str, cfg: PipelineConfig, t0: float) -> AskResult:
        voter = SelfConsistencyVoter(
            vn=self._vn,
            execute_fn=self._execute,
            postprocess_fn=self._postprocess,
            n=cfg.voting_n,
            temperature=cfg.voting_temperature,
            logger=self._log,
        )
        result = voter.run(question)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return AskResult(
            question=result.question,
            sql=result.final_sql,
            executed_ok=result.executed_ok,
            error=result.error,
            df=result.df,
            row_count=row_count(result.df),
            mode="voting",
            correction_iterations=0,
            correction_steps=[],
            was_corrected=False,
            latency_ms=latency_ms,
            confidence=result.confidence,
        )

    def _answer_with_join_paths(self, question: str, cfg: PipelineConfig, t0: float) -> AskResult:
        sql = self._postprocess(self._vn.generate_sql(question=question))
        repaired = False
        if looks_like_sql(sql):
            check = self._join_validator.validate(sql)
            if not check.ok and check.hint:
                self._log.info("join-path repair (%s); re-prompting with FK path", check.reason)
                augmented = f"{question}\n\n{check.hint}"
                sql = self._postprocess(self._vn.generate_sql(question=augmented))
                repaired = True
        df, err = self._run_sql(sql)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return AskResult(
            question=question,
            sql=sql,
            executed_ok=err is None,
            error=err,
            df=df,
            row_count=row_count(df),
            mode="join_paths",
            correction_iterations=1 if repaired else 0,
            correction_steps=[],
            was_corrected=repaired,
            latency_ms=latency_ms,
            confidence=None,
        )

    def _answer_with_value_check(self, question: str, cfg: PipelineConfig, t0: float) -> AskResult:
        sql = self._postprocess(self._vn.generate_sql(question=question))
        repaired = False
        if looks_like_sql(sql):
            check = self._value_validator.validate(sql)
            if not check.ok and check.hint:
                bad = ", ".join(f"{v.column}='{v.value}'" for v in check.violations)
                self._log.info("value-domain repair; out-of-domain literals: %s", bad)
                augmented = f"{question}\n\n{check.hint}"
                sql = self._postprocess(self._vn.generate_sql(question=augmented))
                repaired = True
        df, err = self._run_sql(sql)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return AskResult(
            question=question,
            sql=sql,
            executed_ok=err is None,
            error=err,
            df=df,
            row_count=row_count(df),
            mode="value_check",
            correction_iterations=1 if repaired else 0,
            correction_steps=[],
            was_corrected=repaired,
            latency_ms=latency_ms,
            confidence=None,
        )

    def _run_sql(self, sql: Optional[str]) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        if not looks_like_sql(sql):
            return None, "generation did not return a SQL statement"
        return self._execute(sql)

    def correct(
        self,
        question: str,
        sql: str,
        error: Optional[str] = None,
        max_iters: int = 1,
    ) -> AskResult:
        """Repair a specific query without regenerating from scratch."""
        t0 = time.perf_counter()
        loop = self._build_loop(
            max_iters=max(1, int(max_iters)),
            retry_on_empty=self._config.correction_retry_on_empty,
            repair_temperature=self._config.correction_temperature,
        )
        result = loop.run(question, seed_sql=sql, seed_error=error)
        return self._to_ask_result(result, "self_correction", t0)

    def _build_loop(
        self,
        max_iters: int,
        retry_on_empty: bool,
        repair_temperature: float,
    ) -> SelfCorrectionLoop:
        return SelfCorrectionLoop(
            vn=self._vn,
            execute_fn=self._execute,
            postprocess_fn=self._postprocess,
            dialect=self._dialect,
            max_iters=max_iters,
            retry_on_empty=retry_on_empty,
            repair_temperature=repair_temperature,
            logger=self._log,
        )

    def _to_ask_result(self, result: CorrectionResult, mode: str, t0: float) -> AskResult:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return AskResult(
            question=result.question,
            sql=result.final_sql,
            executed_ok=result.executed_ok,
            error=result.error,
            df=result.df,
            row_count=row_count(result.df),
            mode=mode,
            correction_iterations=result.iterations,
            correction_steps=result.steps,
            was_corrected=result.was_corrected,
            latency_ms=latency_ms,
        )
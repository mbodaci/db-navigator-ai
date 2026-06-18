"""Self-consistency voting over multiple SQL candidates.

A second student-designed control algorithm wrapping the LLM. Instead of trusting
a single generation, it samples several candidate queries at a non-zero
temperature, executes each, and groups them by the *result set they return*
(using the order-independent signature from ``sql_utils``). The query whose
result set the most candidates agree on is chosen, and the level of agreement
gives a confidence score.

This targets the failure mode that execution-guided self-correction structurally
cannot see: a query that executes without error but returns the wrong data. Such
a query is usually a minority answer across samples, so majority voting over
result sets tends to discard it in favour of the consensus.

Dependencies mirror the self-correction loop: a Vanna-style client exposing
``generate_sql`` and a settable ``temperature``, plus an injected ``execute_fn``
and ``postprocess_fn``. Voting only adds value when the sampling temperature is
above zero; with ``n <= 1`` it degenerates to a single generation.
"""
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import pandas as pd

from .sql_utils import looks_like_sql, result_signature, row_count

_EMPTY = "EMPTY"


@dataclass
class Candidate:
    index: int
    sql: Optional[str]
    executed_ok: bool
    error: Optional[str]
    row_count: Optional[int]
    signature: Optional[str]


@dataclass
class VotingResult:
    question: str
    final_sql: Optional[str]
    df: Optional[pd.DataFrame]
    executed_ok: bool
    error: Optional[str]
    n_candidates: int
    n_successful: int
    winning_votes: int
    confidence: float
    candidates: List[Candidate] = field(default_factory=list)
    vote_distribution: dict = field(default_factory=dict)


class SelfConsistencyVoter:

    def __init__(
        self,
        vn,
        execute_fn: Callable[[str], Tuple[Optional[pd.DataFrame], Optional[str]]],
        postprocess_fn: Callable[[Optional[str]], Optional[str]],
        n: int = 5,
        temperature: float = 0.7,
        logger: Optional[logging.Logger] = None,
    ):
        self._vn = vn
        self._execute = execute_fn
        self._postprocess = postprocess_fn
        self._n = max(1, int(n))
        self._temperature = temperature
        self._log = logger or logging.getLogger(__name__)

    def run(self, question: str) -> VotingResult:
        sqls = self._sample_candidates(question)

        candidates: List[Candidate] = []
        groups: dict = {}  # signature -> list of (index, sql, df)
        for i, sql in enumerate(sqls):
            df, err, sig = self._evaluate(sql)
            candidates.append(
                Candidate(
                    index=i,
                    sql=sql,
                    executed_ok=err is None and looks_like_sql(sql),
                    error=err,
                    row_count=row_count(df),
                    signature=sig,
                )
            )
            if sig is not None:
                groups.setdefault(sig, []).append((i, sql, df))

        n_successful = sum(1 for c in candidates if c.executed_ok)

        if not groups:
            error = next((c.error for c in candidates if c.error), "all candidates failed to execute")
            self._log.info("voting: all %d candidates failed to execute", self._n)
            return VotingResult(
                question=question,
                final_sql=candidates[0].sql if candidates else None,
                df=None,
                executed_ok=False,
                error=error,
                n_candidates=self._n,
                n_successful=0,
                winning_votes=0,
                confidence=0.0,
                candidates=candidates,
                vote_distribution={},
            )

        winning_sig = self._pick_winner(groups)
        members = groups[winning_sig]
        winning_votes = len(members)
        final_sql, df = self._representative(members)
        confidence = winning_votes / self._n
        vote_distribution = {sig: len(m) for sig, m in groups.items()}

        self._log.info(
            "voting: %d/%d candidates executed; winner took %d votes (confidence %.2f)",
            n_successful, self._n, winning_votes, confidence,
        )

        return VotingResult(
            question=question,
            final_sql=final_sql,
            df=df,
            executed_ok=True,
            error=None,
            n_candidates=self._n,
            n_successful=n_successful,
            winning_votes=winning_votes,
            confidence=confidence,
            candidates=candidates,
            vote_distribution=vote_distribution,
        )

    def _sample_candidates(self, question: str) -> List[Optional[str]]:
        """Generate ``n`` candidates at the voting temperature, then restore it."""
        previous = getattr(self._vn, "temperature", None)
        sqls: List[Optional[str]] = []
        try:
            if previous is not None:
                self._vn.temperature = self._temperature
            for _ in range(self._n):
                raw = self._vn.generate_sql(question=question)
                sqls.append(self._postprocess(raw))
        finally:
            if previous is not None:
                self._vn.temperature = previous
        return sqls

    def _evaluate(
        self, sql: Optional[str]
    ) -> Tuple[Optional[pd.DataFrame], Optional[str], Optional[str]]:
        if not looks_like_sql(sql):
            return None, "generation did not return a SQL statement", None
        df, err = self._execute(sql)
        if err is not None:
            return None, err, None
        return df, None, result_signature(df)

    def _pick_winner(self, groups: dict) -> str:
        """Most votes wins.

        Ties break in favour of a non-empty result set (an answer returning rows
        is the more plausible consensus for these questions), then by the
        earliest candidate index so the choice is deterministic.
        """
        def sort_key(item):
            sig, members = item
            votes = len(members)
            is_empty = 1 if sig == _EMPTY else 0
            earliest = min(idx for idx, _, _ in members)
            return (-votes, is_empty, earliest)

        winning_sig, _ = min(groups.items(), key=sort_key)
        return winning_sig

    @staticmethod
    def _representative(
        members: List[Tuple[int, Optional[str], Optional[pd.DataFrame]]]
    ) -> Tuple[Optional[str], Optional[pd.DataFrame]]:
        """Pick a representative query from the winning group.

        All members share a result set; choose the most frequent SQL string
        (ties broken by earliest index) and return it with its dataframe.
        """
        counts = Counter(sql for _, sql, _ in members)
        max_count = max(counts.values())
        best = sorted(
            (m for m in members if counts[m[1]] == max_count),
            key=lambda m: m[0],
        )[0]
        return best[1], best[2]

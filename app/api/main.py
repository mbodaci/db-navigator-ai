"""DB-Navigator AI HTTP API.

This module exposes the engine over FastAPI. The engine itself owns the
accuracy logic; this file only wires it to HTTP: it builds Vanna once at
startup, trains the Config F set if the store is empty, caches the inferred
foreign-key relationships for the schema view, and translates requests and
responses to and from the engine.

Server-wide feature defaults come from the environment (``PipelineConfig``).
Individual requests may override the correction flags. Voting is rejected with
501 until that module ships, so the documented baseline is never affected by an
accidental request flag.

Run inside the container:

    uvicorn api.main:app --host 0.0.0.0 --port 8000
"""
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

import config
from api import vanna_setup
from api.schemas import (
    AskRequest,
    AskResponse,
    ColumnModel,
    CorrectionInfo,
    CorrectionStepModel,
    CorrectRequest,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    RelationshipModel,
    SchemaResponse,
    TableModel,
)
from pipeline.engine import AskResult, FeatureNotEnabledError, NLToSQLEngine
from pipeline.flags import PipelineConfig
from pipeline.sql_utils import df_to_records, fix_tsql_syntax

logger = logging.getLogger("dbnav.api")

PERSIST_DIRECTORY = os.getenv("DBNAV_API_CHROMA", "/tmp/vanna_api")
DIALECT = "mssql"
INCLUDE_DESCRIPTIONS = os.getenv("DBNAV_API_INCLUDE_DESCRIPTIONS", "true").strip().lower() in (
    "1", "true", "yes", "on",
)


@dataclass
class AppState:
    ready: bool = False
    detail: Optional[str] = None
    vn: object = None
    engine: Optional[NLToSQLEngine] = None
    source_engine: Optional[Engine] = None
    target_engine: Optional[Engine] = None
    schema: str = "bank"
    model: str = "gpt-4o-mini"
    defaults: PipelineConfig = field(default_factory=PipelineConfig)
    training_counts: dict = field(default_factory=dict)
    fk_candidates: list = field(default_factory=list)


STATE = AppState()


def _build_engines() -> None:
    STATE.source_engine = create_engine(config.SOURCE_DATABASE_URL, pool_pre_ping=True)
    STATE.target_engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)


def _cache_fk_candidates() -> None:
    """Run FK inference once and keep the full candidate objects in memory.

    The schema endpoint reports the inference rationale (match type, inclusion
    percentage, validation), which is only available from the live candidate
    objects; the persisted ``inferred_fks`` table keeps a reduced form used as a
    fallback when this step is unavailable.
    """
    try:
        from enrichment.fk_inference import FKInference

        fk = FKInference(
            source_url="",
            target_url="",
            dialect=DIALECT,
            source_engine=STATE.source_engine,
            target_engine=STATE.target_engine,
        )
        STATE.fk_candidates = list(fk.run(STATE.schema))
        logger.info("Cached %d inferred FK relationships", len(STATE.fk_candidates))
    except Exception as exc:
        STATE.fk_candidates = []
        logger.warning("FK inference unavailable, will fall back to inferred_fks: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    STATE.defaults = PipelineConfig.from_env()
    STATE.schema = getattr(config, "BANK_SCHEMA", "bank")
    api_key = config.OPENAI_API_KEY
    model = getattr(config, "LLM_MODELS", {}).get("openai", "gpt-4o-mini") if hasattr(config, "LLM_MODELS") else "gpt-4o-mini"
    STATE.model = model

    try:
        _build_engines()
        STATE.vn = vanna_setup.build_vanna(PERSIST_DIRECTORY, api_key, model=model)
        STATE.training_counts = vanna_setup.train_config_f(
            STATE.vn,
            source_engine=STATE.source_engine,
            target_engine=STATE.target_engine,
            schema=STATE.schema,
            api_key=api_key,
            dialect=DIALECT,
            include_descriptions=INCLUDE_DESCRIPTIONS,
        )
        _cache_fk_candidates()

        STATE.engine = NLToSQLEngine(
            vn=STATE.vn,
            execute_fn=lambda sql: _execute_source(sql),
            postprocess_fn=fix_tsql_syntax,
            dialect=DIALECT,
            config=STATE.defaults,
            logger=logger,
        )
        STATE.ready = True
        logger.info("API ready (model=%s, defaults=%s)", model, STATE.defaults)
    except Exception as exc:
        STATE.ready = False
        STATE.detail = str(exc)
        logger.exception("Startup failed; service will report not ready")

    yield

    for engine in (STATE.source_engine, STATE.target_engine):
        if engine is not None:
            engine.dispose()


app = FastAPI(
    title="DB-Navigator AI API",
    version="1.0.0",
    description="Natural-language-to-SQL over an enterprise bank database, with an execution-guided self-correction loop.",
    lifespan=lifespan,
)


def _execute_source(sql: str):
    from pipeline.sql_utils import execute_sql

    return execute_sql(STATE.source_engine, sql)


def _require_ready() -> None:
    if not STATE.ready or STATE.engine is None:
        raise HTTPException(
            status_code=503,
            detail=STATE.detail or "Service is starting up or failed to initialise.",
        )


def _reject_voting(cfg: PipelineConfig) -> None:
    if cfg.voting:
        raise HTTPException(
            status_code=501,
            detail="Self-consistency voting is not enabled yet; it ships in a later step.",
        )


def _to_response(result: AskResult, max_rows: int) -> AskResponse:
    columns, rows, truncated = df_to_records(result.df, max_rows=max_rows)
    steps = [
        CorrectionStepModel(
            iteration=s.iteration,
            sql=s.sql,
            executed_ok=s.executed_ok,
            error=s.error,
            row_count=s.row_count,
            action=s.action,
        )
        for s in result.correction_steps
    ]
    correction = CorrectionInfo(
        enabled=result.mode == "self_correction",
        iterations=result.correction_iterations,
        was_corrected=result.was_corrected,
        steps=steps,
    )
    return AskResponse(
        question=result.question,
        sql=result.sql,
        executed_ok=result.executed_ok,
        error=result.error,
        columns=columns,
        rows=rows,
        row_count=result.row_count,
        truncated=truncated,
        mode=result.mode,
        correction=correction,
        latency_ms=result.latency_ms,
        confidence=result.confidence,
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    defaults = STATE.defaults
    return HealthResponse(
        status="ok",
        ready=STATE.ready,
        model=STATE.model,
        schema_name=STATE.schema,
        dialect=DIALECT,
        defaults={
            "self_correction": defaults.self_correction,
            "correction_max_iters": defaults.correction_max_iters,
            "correction_retry_on_empty": defaults.correction_retry_on_empty,
            "correction_temperature": defaults.correction_temperature,
            "voting": defaults.voting,
        },
        training=STATE.training_counts or None,
        detail=STATE.detail,
    )


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, _: None = Depends(_require_ready)) -> AskResponse:
    cfg = STATE.defaults.merged_with(
        self_correction=req.self_correction,
        correction_max_iters=req.max_iters,
        correction_retry_on_empty=req.retry_on_empty,
    )
    _reject_voting(cfg)
    try:
        result = STATE.engine.answer(req.question, config=cfg)
    except FeatureNotEnabledError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception as exc:
        logger.exception("ask failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return _to_response(result, req.max_rows)


@app.post("/correct", response_model=AskResponse)
def correct(req: CorrectRequest, _: None = Depends(_require_ready)) -> AskResponse:
    try:
        result = STATE.engine.correct(
            question=req.question,
            sql=req.sql,
            error=req.error,
            max_iters=req.max_iters,
        )
    except Exception as exc:
        logger.exception("correct failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return _to_response(result, req.max_rows)


@app.post("/feedback", response_model=FeedbackResponse)
def feedback(req: FeedbackRequest, _: None = Depends(_require_ready)) -> FeedbackResponse:
    _log_feedback(req)
    training_added = False
    training_id: Optional[str] = None
    if req.add_to_training:
        try:
            training_id = STATE.vn.train(question=req.question, sql=req.accepted_sql)
            training_added = True
        except Exception as exc:
            logger.warning("Adding feedback to training failed: %s", exc)
    message = "Feedback stored." + (" Added to training." if training_added else "")
    return FeedbackResponse(
        stored=True,
        training_added=training_added,
        training_id=str(training_id) if training_id is not None else None,
        message=message,
    )


def _log_feedback(req: FeedbackRequest) -> None:
    """Append the accepted answer to ``public.query_log`` (best effort)."""
    try:
        with STATE.target_engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO public.query_log
                        (question, generated_sql, executed_ok, execution_error,
                         result_rows, feedback_note, llm_model, latency_ms, created_at)
                    VALUES
                        (:question, :sql, :ok, NULL, NULL, :note, :model, NULL, CURRENT_TIMESTAMP)
                """),
                {
                    "question": req.question,
                    "sql": req.accepted_sql,
                    "ok": True if req.helpful is None else bool(req.helpful),
                    "note": req.note,
                    "model": STATE.model,
                },
            )
    except Exception as exc:
        logger.warning("Writing feedback to query_log failed: %s", exc)


@app.get("/schema", response_model=SchemaResponse)
def schema(
    refresh: bool = Query(default=False, description="Re-run FK inference before responding."),
    _: None = Depends(_require_ready),
) -> SchemaResponse:
    if refresh:
        _cache_fk_candidates()

    tables = _read_tables(STATE.source_engine, STATE.schema)
    relationships = _read_relationships()
    source = "fk_inference" if STATE.fk_candidates else "inferred_fks"
    return SchemaResponse(
        schema_name=STATE.schema,
        dialect=DIALECT,
        tables=tables,
        relationships=relationships,
        source=source,
    )


def _read_tables(engine: Engine, schema: str) -> List[TableModel]:
    tables: List[TableModel] = []
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = :schema AND TABLE_TYPE = 'BASE TABLE'
                ORDER BY TABLE_NAME
            """),
            {"schema": schema},
        ).fetchall()
        for (table_name,) in rows:
            cols = conn.execute(
                text("""
                    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table
                    ORDER BY ORDINAL_POSITION
                """),
                {"schema": schema, "table": table_name},
            ).fetchall()
            columns = [
                ColumnModel(name=c[0], type=c[1], nullable=(c[2] == "YES"))
                for c in cols
            ]
            tables.append(TableModel(name=table_name, columns=columns, row_count=None))
    return tables


def _read_relationships() -> List[RelationshipModel]:
    if STATE.fk_candidates:
        return [
            RelationshipModel(
                src_table=c.src_table,
                src_column=c.src_column,
                tgt_table=c.tgt_table,
                tgt_column=c.tgt_column,
                confidence=float(c.confidence),
                validated=bool(c.validated),
                inference_method=c.inference_method,
                match_type=getattr(c, "match_type", None),
                inclusion_pct=getattr(c, "inclusion_pct", None),
            )
            for c in STATE.fk_candidates
        ]
    return _read_relationships_fallback()


def _read_relationships_fallback() -> List[RelationshipModel]:
    """Read persisted FK rows from ``public.inferred_fks`` (reduced fields)."""
    out: List[RelationshipModel] = []
    try:
        with STATE.target_engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT src_table, src_column, tgt_table, tgt_column,
                           inference_method, confidence, validated
                    FROM public.inferred_fks
                    WHERE src_schema = :schema
                    ORDER BY src_table, src_column
                """),
                {"schema": STATE.schema},
            ).fetchall()
        for r in rows:
            out.append(
                RelationshipModel(
                    src_table=r[0],
                    src_column=r[1],
                    tgt_table=r[2],
                    tgt_column=r[3],
                    inference_method=r[4],
                    confidence=float(r[5]) if r[5] is not None else 0.0,
                    validated=bool(r[6]),
                    match_type=None,
                    inclusion_pct=None,
                )
            )
    except Exception as exc:
        logger.warning("Reading inferred_fks failed: %s", exc)
    return out

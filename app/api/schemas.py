"""Request and response models for the DB-Navigator AI API."""
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    self_correction: Optional[bool] = Field(
        default=None,
        description="Override the server default for the self-correction loop.",
    )
    max_iters: Optional[int] = Field(
        default=None, ge=0, le=5,
        description="Override the maximum number of repair iterations.",
    )
    retry_on_empty: Optional[bool] = Field(
        default=None,
        description="Treat an empty result set as a fault worth repairing.",
    )
    max_rows: int = Field(default=200, ge=1, le=5000)


class CorrectRequest(BaseModel):
    question: str = Field(..., min_length=1)
    sql: str = Field(..., min_length=1)
    error: Optional[str] = Field(
        default=None,
        description="The database error, if known. If omitted, the SQL is executed to obtain it.",
    )
    max_iters: int = Field(default=1, ge=1, le=5)
    max_rows: int = Field(default=200, ge=1, le=5000)


class FeedbackRequest(BaseModel):
    question: str = Field(..., min_length=1)
    accepted_sql: str = Field(..., min_length=1)
    helpful: Optional[bool] = None
    note: Optional[str] = None
    add_to_training: bool = Field(
        default=True,
        description="Store the (question, SQL) pair as a new training example.",
    )


class CorrectionStepModel(BaseModel):
    iteration: int
    sql: Optional[str] = None
    executed_ok: bool
    error: Optional[str] = None
    row_count: Optional[int] = None
    action: str


class CorrectionInfo(BaseModel):
    enabled: bool
    iterations: int
    was_corrected: bool
    steps: List[CorrectionStepModel] = Field(default_factory=list)


class AskResponse(BaseModel):
    question: str
    sql: Optional[str] = None
    executed_ok: bool
    error: Optional[str] = None
    columns: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    row_count: Optional[int] = None
    truncated: bool = False
    mode: str
    correction: CorrectionInfo
    latency_ms: int
    confidence: Optional[float] = None


class FeedbackResponse(BaseModel):
    stored: bool
    training_added: bool
    training_id: Optional[str] = None
    message: str


class ColumnModel(BaseModel):
    name: str
    type: str
    nullable: bool


class TableModel(BaseModel):
    name: str
    columns: List[ColumnModel] = Field(default_factory=list)
    row_count: Optional[int] = None


class RelationshipModel(BaseModel):
    src_table: str
    src_column: str
    tgt_table: str
    tgt_column: str
    confidence: float
    validated: bool
    inference_method: str
    match_type: Optional[str] = None
    inclusion_pct: Optional[float] = None


class SchemaResponse(BaseModel):
    schema_name: str
    dialect: str
    tables: List[TableModel] = Field(default_factory=list)
    relationships: List[RelationshipModel] = Field(default_factory=list)
    source: str


class HealthResponse(BaseModel):
    status: str
    ready: bool
    model: Optional[str] = None
    schema_name: Optional[str] = None
    dialect: Optional[str] = None
    defaults: dict = Field(default_factory=dict)
    training: Optional[dict] = None
    detail: Optional[str] = None

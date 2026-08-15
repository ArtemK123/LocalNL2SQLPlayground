from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    db_id: str | None = Field(default=None, max_length=128)
    evidence: str | None = Field(default=None, max_length=4000)


class ChatResponse(BaseModel):
    answer: str
    sql: str
    columns: list[str]
    rows: list[dict]
    model_used: str
    execution_ms: int
    total_ms: int
    reasoning_summary: str
    schema_selection: dict | None = None


class HealthResponse(BaseModel):
    status: str

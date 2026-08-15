from __future__ import annotations

import logging
import time
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.agent import SqlAgent
from app.config import settings
from app.db import create_db_engine, run_read_query
from app.models import ChatRequest, ChatResponse, HealthResponse
from app.sql_guard import sanitize_prompt, validate_safe_question

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("langchain-api")

app = FastAPI(title="Doris-test LangChain NL2SQL API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = create_db_engine()
agent = SqlAgent(engine=engine)
stats_lock = Lock()
stats = {"requests_total": 0, "errors_total": 0}


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    with stats_lock:
        payload = (
            f"nl2sql_requests_total {stats['requests_total']}\n"
            f"nl2sql_errors_total {stats['errors_total']}\n"
        )
    return payload


@app.post("/v1/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    started_at = time.perf_counter()

    with stats_lock:
        stats["requests_total"] += 1

    question = sanitize_prompt(payload.question)
    if not question:
        with stats_lock:
            stats["errors_total"] += 1
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        validate_safe_question(question)
    except ValueError as exc:
        with stats_lock:
            stats["errors_total"] += 1
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        sql, model_used, selection = agent.generate_sql(
            question,
            db_id=payload.db_id,
            evidence=payload.evidence,
        )
    except Exception as exc:
        with stats_lock:
            stats["errors_total"] += 1
        raise HTTPException(status_code=400, detail=f"SQL generation failed: {exc}") from exc

    exec_mode = (settings.sql_exec_mode or "execute").strip().lower()
    skip_exec = exec_mode in {"skip", "none", "off", "generate_only"}

    columns: list[str] = []
    rows: list = []
    execution_ms = 0
    if not skip_exec:
        execution_error: Exception | None = None
        for _attempt in range(settings.sql_repair_max_retries + 1):
            try:
                columns, rows, execution_ms = run_read_query(engine, sql)
                execution_error = None
                break
            except Exception as exc:
                execution_error = exc
                if _attempt >= settings.sql_repair_max_retries:
                    break
                try:
                    sql, model_used = agent.repair_sql(
                        question=question,
                        failed_sql=sql,
                        error_message=str(exc),
                        selection=selection,
                        model_used=model_used,
                    )
                except Exception:
                    break
        if execution_error is not None:
            with stats_lock:
                stats["errors_total"] += 1
            # Include SQL so harness can salvage pred for dual-DSN scoring.
            raise HTTPException(
                status_code=400,
                detail=f"SQL execution failed: {execution_error} [SQL: {sql}]",
            ) from execution_error

    if settings.nl2sql_fast_mode or skip_exec:
        answer = f"Returned {len(rows)} row(s)." if not skip_exec else "SQL generated (exec skipped)."
        reasoning_summary = (
            "Generated SQL from the question using schema-selected tables and validated read-only rules."
        )
    else:
        try:
            answer = agent.summarize(question=question, sql=sql, columns=columns, rows=rows)
        except Exception:
            log.exception("Falling back to templated summary after LLM summarization error.")
            answer = f"Returned {len(rows)} rows for your request."

        try:
            reasoning_summary = agent.explain_sql(question=question, sql=sql, columns=columns)
        except Exception:
            log.exception("Falling back to templated reasoning after LLM explanation error.")
            reasoning_summary = (
                "Generated a read-only SQL query from your question, validated safety rules, "
                "executed it against allowed schemas, and returned the result."
            )
    total_ms = int((time.perf_counter() - started_at) * 1000)
    schema_selection = None
    if settings.schema_selection_enabled or settings.schema_selection_debug:
        schema_selection = {
            "enabled": settings.schema_selection_enabled,
            "selector_mode": settings.schema_selector_mode,
            "shortlist_top_m": settings.schema_shortlist_top_m,
            "final_top_k": settings.schema_final_top_k,
            "selected_tables": list(selection.selected_table_fq),
            "allowed_tables": list(selection.allowed_table_fq),
            "selected_table_count": len(selection.selected_table_fq),
            "used_fallback_full_schema": selection.used_fallback_full_schema,
            "arctic_sql_dialect": settings.arctic_sql_dialect,
            "llm_backend": settings.llm_backend,
            "sql_exec_mode": settings.sql_exec_mode,
            "schema_source": settings.schema_source,
            "db_id": payload.db_id or selection.db_id,
            "db_id_as_schema": settings.db_id_as_schema,
        }

    return ChatResponse(
        answer=answer,
        sql=sql,
        columns=columns,
        rows=rows,
        model_used=model_used,
        execution_ms=execution_ms,
        total_ms=total_ms,
        reasoning_summary=reasoning_summary,
        schema_selection=schema_selection,
    )

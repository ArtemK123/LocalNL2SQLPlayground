from __future__ import annotations

import logging
import time
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

from app.agent import SqlAgent
from app.config import settings
from app.db import create_db_engine, run_read_query
from app.models import ChatRequest, ChatResponse, HealthResponse
from app.sql_guard import sanitize_prompt, validate_safe_question
from app.sql_lint import empty_result_repair_message, lint_generated_sql

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("langchain-api")

app = FastAPI(title="Local LangChain NL2SQL API", version="0.1.0")
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

    repairs_left = settings.sql_repair_max_retries
    llm_calls = 1

    lint_issues = lint_generated_sql(sql, question, selection)
    if lint_issues and repairs_left > 0:
        try:
            sql, model_used = agent.repair_sql(
                question=question,
                failed_sql=sql,
                error_message="SQL lint: " + "; ".join(lint_issues),
                selection=selection,
                model_used=model_used,
            )
            repairs_left -= 1
            llm_calls += 1
        except Exception:
            log.exception("Post-generation SQL lint repair failed; continuing with original SQL.")

    exec_mode = (settings.sql_exec_mode or "execute").strip().lower()
    skip_exec = exec_mode in {"skip", "none", "off", "generate_only"}

    execution_error: Exception | None = None
    columns: list[str] = []
    rows: list = []
    execution_ms = 0
    if skip_exec:
        columns, rows, execution_ms = [], [], 0
    else:
        while True:
            try:
                columns, rows, execution_ms = run_read_query(engine, sql)
                execution_error = None
            except Exception as exc:
                execution_error = exc
                if repairs_left <= 0:
                    break
                try:
                    sql, model_used = agent.repair_sql(
                        question=question,
                        failed_sql=sql,
                        error_message=str(exc),
                        selection=selection,
                        model_used=model_used,
                    )
                    repairs_left -= 1
                    llm_calls += 1
                except Exception:
                    break
                continue

            if rows or repairs_left <= 0:
                break
            try:
                sql, model_used = agent.repair_sql(
                    question=question,
                    failed_sql=sql,
                    error_message=empty_result_repair_message(sql, question),
                    selection=selection,
                    model_used=model_used,
                )
                repairs_left -= 1
                llm_calls += 1
            except Exception:
                break

        if execution_error is not None:
            with stats_lock:
                stats["errors_total"] += 1
            raise HTTPException(status_code=400, detail=f"SQL execution failed: {execution_error}") from execution_error

    if settings.nl2sql_fast_mode:
        answer = (
            "Generated SQL (server-side execution skipped)."
            if skip_exec
            else f"Returned {len(rows)} row(s)."
        )
        reasoning_summary = (
            "Generated SQL from the question using schema-selected tables "
            "and validated read-only rules."
            + (" Server-side execution skipped." if skip_exec else " Executed against the database.")
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
            "bird_db_profile": settings.bird_db_profile,
            "db_id": selection.db_id,
            "selected_tables": list(selection.selected_table_fq),
            "allowed_tables": list(selection.allowed_table_fq),
            "selected_table_count": len(selection.selected_table_fq),
            "used_fallback_full_schema": selection.used_fallback_full_schema,
            "llm_calls": llm_calls,
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

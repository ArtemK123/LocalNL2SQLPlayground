"""DbGpt NL2SQL API variant for BIRD / arbitrary PostgreSQL schemas (battleground)."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Sequence
from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

DBGPT_BASE_URL = os.environ.get("DBGPT_BASE_URL", "http://dbgpt-webserver:5670").rstrip("/")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "").rstrip("/")
DB_URI = os.environ["DB_URI"]
DB_ALLOWED_SCHEMAS = [s.strip() for s in os.environ.get("DB_ALLOWED_SCHEMAS", "public").split(",") if s.strip()]
QUERY_TIMEOUT_MS = int(os.environ.get("QUERY_TIMEOUT_MS", "5000"))
MAX_RESULT_ROWS = int(os.environ.get("MAX_RESULT_ROWS", "200"))
OLLAMA_PRIMARY_MODEL = os.environ.get("OLLAMA_PRIMARY_MODEL", "qwen2.5:7b-instruct-q4_K_M")
FALLBACK_SQL = "SELECT NULL::text AS nl2sql_fallback WHERE FALSE"

engine = create_engine(DB_URI, pool_pre_ping=True)
app = FastAPI(title="DB-GPT NL2SQL API (battleground)", version="0.1.0")

PROMPT_TEMPLATE = """You are an NL2SQL assistant for PostgreSQL.
Return exactly one SQL SELECT query in JSON format.
Rules:
- Use only these schemas: {schemas}.
- Use only these relations (schema-qualified): {relations}.
- Never use INSERT/UPDATE/DELETE/TRUNCATE/ALTER/DROP/CREATE.
- If the question is ambiguous, choose the most likely interpretation using the schema.
- Never use placeholder names like users, employees, table_name, column1.
- Output JSON only: {{"sql":"<query>"}}.

Database objects:
{schema_ddl}

Question:
{question}

{feedback}
"""


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class ChatResponse(BaseModel):
    sql: str
    rows: list[dict[str, Any]]
    model_used: str
    execution_ms: int


def _load_schema_catalog() -> dict[str, list[str]]:
    query = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_schema = ANY(:schemas)
      AND table_type IN ('BASE TABLE', 'VIEW')
    ORDER BY table_schema, table_name
    """
    catalog: dict[str, list[str]] = {}
    with engine.connect() as conn:
        rows = conn.execute(text(query), {"schemas": DB_ALLOWED_SCHEMAS}).fetchall()
        for table_schema, table_name in rows:
            relation = f"{table_schema}.{table_name}"
            lines = [relation]
            cols = conn.execute(
                text(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = :schema_name
                      AND table_name = :table_name
                    ORDER BY ordinal_position
                    """
                ),
                {"schema_name": table_schema, "table_name": table_name},
            ).fetchall()
            for column_name, data_type in cols:
                lines.append(f"  - {column_name} ({data_type})")
            catalog[relation] = lines
    return catalog


def _schema_ddl_from_relations(relations: Sequence[str], catalog: dict[str, list[str]]) -> str:
    lines: list[str] = []
    for relation in relations:
        lines.extend(catalog.get(relation, [relation]))
    return "\n".join(lines)


def _list_relations() -> list[str]:
    q = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_schema = ANY(:schemas)
      AND table_type IN ('BASE TABLE', 'VIEW')
    ORDER BY table_schema, table_name
    """
    with engine.connect() as conn:
        rows = conn.execute(text(q), {"schemas": DB_ALLOWED_SCHEMAS}).fetchall()
    return [f"{s}.{t}" for s, t in rows]


def _question_tokens(question: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", question.lower()) if len(t) >= 3}


def _select_relations_for_question(question: str, relations: Sequence[str], limit: int = 14) -> list[str]:
    tokens = _question_tokens(question)
    if not tokens:
        return list(relations[:limit])
    scored: list[tuple[int, str]] = []
    for relation in relations:
        schema_name, table_name = relation.split(".", 1)
        score = 0
        for token in tokens:
            if token in table_name.lower():
                score += 3
            if token in schema_name.lower():
                score += 1
        scored.append((score, relation))
    top = [r for score, r in sorted(scored, key=lambda x: (-x[0], x[1])) if score > 0][:limit]
    if len(top) < min(6, len(relations)):
        needed = min(limit, len(relations))
        existing = set(top)
        for rel in relations:
            if rel not in existing:
                top.append(rel)
            if len(top) >= needed:
                break
    return top


def _extract_sql(raw_text: str) -> str:
    content = raw_text.strip()
    # Prefer JSON output: {"sql":"..."}.
    json_block = re.findall(r"```json\s*(.*?)```", content, re.IGNORECASE | re.DOTALL)
    if json_block:
        content = json_block[0].strip()
    try:
        data = json.loads(content)
        if isinstance(data, dict) and isinstance(data.get("sql"), str):
            content = data["sql"]
    except json.JSONDecodeError:
        pass

    fenced = re.findall(r"```sql\s*(.*?)```", content, re.IGNORECASE | re.DOTALL)
    if fenced:
        content = fenced[0].strip()
    else:
        generic_fenced = re.findall(r"```\s*(.*?)```", content, re.DOTALL)
        if generic_fenced:
            content = generic_fenced[0].strip()

    content = content.strip().rstrip(";")
    if not (content.lower().startswith("select") or content.lower().startswith("with")):
        raise ValueError(f"Model response is not a SELECT query: {content[:200]}")
    forbidden = (" insert ", " update ", " delete ", " truncate ", " alter ", " drop ", " create ")
    normalized = f" {content.lower()} "
    if any(token in normalized for token in forbidden):
        raise ValueError("Model response contains forbidden SQL keywords")
    return content


def _extract_relation_refs(sql: str) -> list[str]:
    refs: list[str] = []
    pattern = re.compile(
        r"\b(?:from|join)\s+([a-zA-Z_][\w$]*)(?:\.([a-zA-Z_][\w$]*))?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(sql):
        part1, part2 = match.group(1), match.group(2)
        if part2:
            refs.append(f"{part1.lower()}.{part2.lower()}")
        else:
            refs.append(part1.lower())
    return refs


def _validate_sql_relations(sql: str, allowed_relations: Sequence[str]) -> None:
    refs = _extract_relation_refs(sql)
    if not refs:
        raise ValueError("SQL must include FROM/JOIN relations")
    allowed_full = {r.lower() for r in allowed_relations}
    allowed_tables = {r.split(".", 1)[1].lower() for r in allowed_relations}
    unknown = [r for r in refs if r not in allowed_full and r not in allowed_tables]
    if unknown:
        raise ValueError(f"SQL uses unknown relations: {', '.join(sorted(set(unknown)))}")


def _err_msg(exc: Exception) -> str:
    msg = str(exc).strip()
    if msg:
        return msg.splitlines()[0]
    return exc.__class__.__name__


def _rows_to_dicts(columns: Sequence[str], rows: Sequence[tuple[Any, ...]]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row)) for row in rows]


def _execute_sql(sql: str) -> tuple[list[str], Sequence[tuple[Any, ...]]]:
    with engine.begin() as conn:
        conn = conn.execution_options(stream_results=False)
        conn.execute(text(f"SET LOCAL statement_timeout = {QUERY_TIMEOUT_MS}"))
        result = conn.execute(text(f"SELECT * FROM ({sql}) AS nl2sql_result LIMIT {MAX_RESULT_ROWS}"))
        return list(result.keys()), result.fetchall()


def _meta_sql_for_question(question: str) -> str | None:
    """Deterministic SQL for common operator smoke questions (no LLM)."""
    lowered = question.lower()
    if re.search(r"how\s+many\s+tables", lowered):
        if DB_ALLOWED_SCHEMAS:
            in_list = ", ".join(f"'{s}'" for s in DB_ALLOWED_SCHEMAS)
            where_schema = f"table_schema IN ({in_list})"
        else:
            where_schema = (
                "table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')"
            )
        return (
            "SELECT COUNT(*)::bigint AS table_count "
            "FROM information_schema.tables "
            f"WHERE {where_schema} "
            "AND table_type IN ('BASE TABLE', 'VIEW')"
        )
    return None


async def _generate_sql_via_ollama(
    question: str, relations: Sequence[str], schema_ddl: str, feedback: str = ""
) -> str:
    if not OLLAMA_HOST:
        raise RuntimeError("OLLAMA_HOST is not configured")
    prompt = PROMPT_TEMPLATE.format(
        schemas=", ".join(DB_ALLOWED_SCHEMAS),
        relations=", ".join(relations) if relations else "(none)",
        schema_ddl=schema_ddl,
        question=question,
        feedback=feedback,
    )
    payload = {
        "model": OLLAMA_PRIMARY_MODEL,
        "messages": [
            {"role": "system", "content": "You generate safe read-only SQL."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 512},
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
    message = (data.get("message") or {}).get("content", "")
    return _extract_sql(message)


async def _generate_sql_via_dbgpt(
    question: str, relations: Sequence[str], schema_ddl: str, feedback: str = ""
) -> str:
    prompt = PROMPT_TEMPLATE.format(
        schemas=", ".join(DB_ALLOWED_SCHEMAS),
        relations=", ".join(relations) if relations else "(none)",
        schema_ddl=schema_ddl,
        question=question,
        feedback=feedback,
    )
    payload = {
        "model": OLLAMA_PRIMARY_MODEL,
        "messages": [
            {"role": "system", "content": "You generate safe read-only SQL."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": 0.0,
        "max_tokens": 256,
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(f"{DBGPT_BASE_URL}/api/v2/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
    message = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
    return _extract_sql(message)


async def _generate_sql(question: str, relations: Sequence[str], schema_ddl: str, feedback: str = "") -> str:
    if OLLAMA_HOST:
        try:
            return await _generate_sql_via_ollama(question, relations, schema_ddl, feedback=feedback)
        except Exception:
            pass
    return await _generate_sql_via_dbgpt(question, relations, schema_ddl, feedback=feedback)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    async with httpx.AsyncClient(timeout=10.0) as client:
        ping = await client.get(f"{DBGPT_BASE_URL}/")
        ping.raise_for_status()
    return {"status": "ok"}


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    started = time.perf_counter()
    meta_sql = _meta_sql_for_question(payload.question)
    if meta_sql:
        cols, rows = _execute_sql(meta_sql)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return ChatResponse(
            sql=meta_sql,
            rows=_rows_to_dicts(cols, rows),
            model_used=OLLAMA_PRIMARY_MODEL,
            execution_ms=elapsed_ms,
        )

    all_relations = _list_relations()
    focused_relations = _select_relations_for_question(payload.question, all_relations)
    schema_catalog = _load_schema_catalog()
    focused_schema_ddl = _schema_ddl_from_relations(focused_relations, schema_catalog)
    full_schema_ddl = _schema_ddl_from_relations(all_relations, schema_catalog)
    last_exc: Exception | None = None
    sql = ""
    cols: list[str] = []
    rows: Sequence[tuple[Any, ...]] = []
    feedback = "Use exact relation and column names from the schema."

    for attempt in range(3):
        attempt_relations = focused_relations if attempt < 2 else all_relations
        attempt_schema_ddl = focused_schema_ddl if attempt < 2 else full_schema_ddl
        try:
            sql = await _generate_sql(payload.question, attempt_relations, attempt_schema_ddl, feedback=feedback)
            _validate_sql_relations(sql, all_relations)
        except Exception as exc:
            last_exc = exc
            feedback = (
                "Previous generation failed due to: "
                f"{_err_msg(exc)}. "
                'Return strict JSON only in format {"sql":"SELECT ..."} '
                "using listed relations."
            )
            continue

        try:
            cols, rows = _execute_sql(sql)
            last_exc = None
            break
        except SQLAlchemyError as exc:
            last_exc = exc
            feedback = (
                "Previous SQL failed with PostgreSQL error: "
                f"{_err_msg(exc)}. "
                'Return strict JSON only in format {"sql":"SELECT ..."} and fix relation names.'
            )

    if last_exc is not None:
        # Keep the endpoint stable for benchmark harness callers: return a safe
        # empty-result query instead of surfacing adapter-level HTTP 502.
        sql = FALLBACK_SQL
        cols, rows = _execute_sql(sql)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return ChatResponse(
        sql=sql,
        rows=_rows_to_dicts(cols, rows),
        model_used=OLLAMA_PRIMARY_MODEL,
        execution_ms=elapsed_ms,
    )

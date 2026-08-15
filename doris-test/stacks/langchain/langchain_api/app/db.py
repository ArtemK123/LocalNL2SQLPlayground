from __future__ import annotations

import time
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import settings


def create_db_engine() -> Engine:
    return create_engine(settings.db_uri, pool_pre_ping=True, future=True)


def run_read_query(engine: Engine, sql: str) -> tuple[list[str], list[dict[str, Any]], int]:
    start = time.perf_counter()
    wrapped_sql = f"SELECT * FROM ({sql}) AS q LIMIT :max_rows"
    # psycopg cannot bind parameters into SET the same way as DML; use a clamped int (ms).
    timeout_ms = max(1, min(int(settings.query_timeout_ms), 86_400_000))
    with engine.connect() as conn:
        if settings.is_mysql:
            conn.execute(text(f"SET max_execution_time = {timeout_ms}"))
        else:
            conn.execute(text(f"SET statement_timeout = {timeout_ms}"))
        result = conn.execute(text(wrapped_sql), {"max_rows": settings.max_result_rows})
        rows = [dict(row._mapping) for row in result]
        cols = list(result.keys())
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return cols, rows, elapsed_ms

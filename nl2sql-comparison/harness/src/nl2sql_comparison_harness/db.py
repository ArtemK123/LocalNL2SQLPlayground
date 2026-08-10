from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

_INT_STRING = re.compile(r"^-?(0|[1-9]\d*)$")
_FLOAT_STRING = re.compile(r"^-?(0|[1-9]\d*)(\.\d+)([eE][+-]?\d+)?$")
_WRAP_LIMIT_RE = re.compile(
    r"(?is)^\s*SELECT\s+\*\s+FROM\s*\((.*)\)\s+AS\s+\w+\s+LIMIT\s+(?:\d+|%\([^)]+\)s)\s*;?\s*$"
)


def strip_exec_wrapper(sql: str) -> str:
    """Remove API/harness SELECT * FROM (...) AS q LIMIT N wrappers if present."""
    text = (sql or "").strip().rstrip(";")
    m = _WRAP_LIMIT_RE.match(text)
    if m:
        return m.group(1).strip().rstrip(";")
    return text


def run_query(
    dsn: str,
    sql: str,
    *,
    timeout_ms: int = 60_000,
    max_rows: int = 500,
) -> tuple[list[str], list[dict[str, Any]]]:
    sql = strip_exec_wrapper(sql)
    wrapped = f"SELECT * FROM ({sql}) AS _bird_q LIMIT {int(max_rows)}"
    with psycopg.connect(dsn, connect_timeout=30) as conn:
        conn.execute(f"SET statement_timeout = {int(timeout_ms)}")
        with conn.cursor() as cur:
            # Use server-side prepared=False path; escape % that may appear in SQL literals.
            cur.execute(wrapped.replace("%", "%%"))
            cols = [d.name for d in cur.description] if cur.description else []
            raw = cur.fetchall()
    rows: list[dict[str, Any]] = []
    for tup in raw:
        rows.append(dict(zip(cols, tup)))
    return cols, rows


def resolve_sqlite_db_path(databases_dir: str | Path, db_id: str) -> Path:
    base = Path(databases_dir)
    return base / db_id / f"{db_id}.sqlite"


def run_query_sqlite(
    db_path: str | Path,
    sql: str,
    *,
    timeout_ms: int = 60_000,
    max_rows: int = 500,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Execute SQL against a BIRD minidev SQLite file (Study Gen EX path)."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {path}")
    sql = strip_exec_wrapper(sql)
    timeout_s = max(0.1, float(timeout_ms) / 1000.0)
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=min(5.0, timeout_s))
    try:
        conn.execute(f"PRAGMA busy_timeout = {int(min(5.0, timeout_s) * 1000)}")
        deadline = time.monotonic() + timeout_s

        def _on_progress(*_args: Any) -> int:
            if time.monotonic() > deadline:
                raise TimeoutError(f"SQL query exceeded {timeout_s}s wall-clock timeout")
            return 0

        conn.set_progress_handler(_on_progress, 5_000)
        cur = conn.cursor()
        cur.execute(sql)
        if cur.description is None:
            return [], []
        cols = [d[0] for d in cur.description]
        raw = cur.fetchmany(int(max_rows) + 1) if max_rows > 0 else cur.fetchall()
        if max_rows > 0 and len(raw) > max_rows:
            raw = raw[:max_rows]
        rows = [dict(zip(cols, tup)) for tup in raw]
        return cols, rows
    finally:
        try:
            conn.set_progress_handler(None, 0)
        except Exception:  # noqa: BLE001
            pass
        conn.close()


def normalize_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return int(v) if v == int(v) else float(v)
    if isinstance(v, float):
        return int(v) if v == int(v) else v
    if isinstance(v, str):
        s = v.strip()
        if _INT_STRING.fullmatch(s):
            return int(s)
        if _FLOAT_STRING.fullmatch(s):
            return float(s)
        return v
    if isinstance(v, (bytes, bytearray)):
        return normalize_value(v.decode("utf-8", errors="replace"))
    if isinstance(v, memoryview):
        return normalize_value(bytes(v).decode("utf-8", errors="replace"))
    return v


def project_row(row: dict[str, Any], gold_columns: Sequence[str], col_map: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    lk = {k.lower(): k for k in row}
    for gcol in gold_columns:
        pk = col_map.get(gcol.lower())
        if pk and pk in row:
            out[gcol] = normalize_value(row[pk])
        elif gcol.lower() in lk:
            out[gcol] = normalize_value(row[lk[gcol.lower()]])
        else:
            out[gcol] = None
    return out


def multiset_signatures(rows: list[dict[str, Any]], column_order: Sequence[str]) -> list[tuple[Any, ...]]:
    sigs = []
    for r in rows:
        sigs.append(tuple(normalize_value(r.get(c)) for c in column_order))
    return sorted(sigs, key=lambda t: repr(t))


def match_columns_case_insensitive(gold_cols: list[str], pred_cols: list[str]) -> dict[str, str]:
    pred_by_lower = {c.lower(): c for c in pred_cols}
    mapping: dict[str, str] = {}
    for g in gold_cols:
        gl = g.lower()
        if gl in pred_by_lower:
            mapping[gl] = pred_by_lower[gl]
    # Scalar results often differ only by alias (?column? vs percentage).
    if len(gold_cols) == 1 and len(pred_cols) == 1 and not mapping:
        mapping[gold_cols[0].lower()] = pred_cols[0]
    return mapping

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

_INT_STRING = re.compile(r"^-?(0|[1-9]\d*)$")
_FLOAT_STRING = re.compile(r"^-?(0|[1-9]\d*)(\.\d+)([eE][+-]?\d+)?$")
# ISO-ish timestamps commonly emitted by PG vs Doris drivers.
_TS_STRING = re.compile(
    r"^(\d{4}-\d{2}-\d{2})"
    r"(?:[ T](\d{2}:\d{2}:\d{2}(?:\.\d+)?))?$"
)


def _scheme(dsn: str) -> str:
    return urlparse(dsn).scheme.split("+", 1)[0].lower()


def dedupe_column_names(cols: list[str]) -> list[str]:
    """Keep positional identity when drivers repeat names (``?column?``)."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for c in cols:
        n = seen.get(c, 0)
        seen[c] = n + 1
        out.append(c if n == 0 else f"{c}__{n + 1}")
    return out


def _matching_close_paren(sql: str, open_idx: int) -> int | None:
    depth = 0
    in_quote = False
    i = open_idx
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_quote:
            in_quote = True
        elif ch == "'" and in_quote:
            if i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            in_quote = False
        elif not in_quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return None


def rewrite_scalar_eq_subqueries_for_doris(sql: str) -> str:
    """Rewrite ``col = (SELECT ...)`` to ``col IN (SELECT ...)`` for Doris.

    Uncorrelated scalar equality is cancelled (``SCALARSUBQUERY`` / Expected EQ 1).
    Applies to any SQL; not a named table or question.
    """
    replacements: list[tuple[int, int]] = []
    i = 0
    in_quote = False
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_quote:
            in_quote = True
            i += 1
            continue
        if ch == "'" and in_quote:
            if i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            in_quote = False
            i += 1
            continue
        if in_quote:
            i += 1
            continue
        if (
            ch == "="
            and (i == 0 or sql[i - 1] not in "<>=!")
            and (i + 1 >= len(sql) or sql[i + 1] != "=")
        ):
            j = i + 1
            while j < len(sql) and sql[j].isspace():
                j += 1
            if j < len(sql) and sql[j] == "(":
                k = j + 1
                while k < len(sql) and sql[k].isspace():
                    k += 1
                if sql[k : k + 6].upper() == "SELECT":
                    end = _matching_close_paren(sql, j)
                    if end is not None:
                        replacements.append((i, j))
                        i = end + 1
                        continue
        i += 1
    if not replacements:
        return sql
    out = sql
    for eq_pos, open_pos in reversed(replacements):
        out = out[:eq_pos].rstrip() + " IN " + out[open_pos:]
    return out


def run_query(
    dsn: str,
    sql: str,
    *,
    timeout_ms: int = 60_000,
    max_rows: int = 500,
    schema: str | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    sql = sql.strip().rstrip(";")
    wrapped = f"SELECT * FROM ({sql}) AS _bird_q LIMIT {int(max_rows)}"
    scheme = _scheme(dsn)

    if scheme in ("postgresql", "postgres"):
        import psycopg

        with psycopg.connect(dsn, connect_timeout=30) as conn:
            conn.execute(f"SET statement_timeout = {int(timeout_ms)}")
            # BIRD gold SQL uses unqualified names; map db_id -> schema search_path.
            if schema:
                safe = schema.replace('"', "")
                conn.execute(f'SET search_path TO "{safe}", public')
            with conn.cursor() as cur:
                cur.execute(wrapped)
                cols = [d.name for d in cur.description] if cur.description else []
                raw = cur.fetchall()
    elif scheme == "mysql":
        import pymysql

        sql = rewrite_scalar_eq_subqueries_for_doris(sql)
        wrapped = f"SELECT * FROM ({sql}) AS _bird_q LIMIT {int(max_rows)}"
        parsed = urlparse(dsn)
        conn = pymysql.connect(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 3306,
            user=parsed.username or "root",
            password=parsed.password or "",
            database=(parsed.path or "/").lstrip("/"),
            connect_timeout=30,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(f"SET max_execution_time = {int(timeout_ms)}")
                # Doris: prefer USE <db_id> so unqualified/qualified names resolve.
                if schema:
                    safe = schema.replace("`", "")
                    try:
                        cur.execute(f"USE `{safe}`")
                    except Exception:
                        pass
                cur.execute(wrapped)
                cols = [d[0] for d in cur.description] if cur.description else []
                raw = cur.fetchall()
        finally:
            conn.close()
    else:
        raise ValueError(f"Unsupported DSN scheme: {scheme}")

    cols = dedupe_column_names(list(cols))
    rows: list[dict[str, Any]] = []
    for tup in raw:
        rows.append(dict(zip(cols, tup)))
    return cols, rows


def normalize_value(v: Any) -> Any:
    """Normalize cell values for cross-engine multiset compare (PG ↔ Doris)."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, Decimal):
        try:
            return int(v) if v == v.to_integral_value() else float(v)
        except (InvalidOperation, ValueError):
            return float(v)
    if isinstance(v, float):
        return int(v) if v.is_integer() else v
    if isinstance(v, datetime):
        return v.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, time):
        return v.replace(tzinfo=None).isoformat(timespec="seconds")
    if isinstance(v, str):
        s = v.strip()
        if s.lower() in {"null", "none", ""}:
            return None if s.lower() in {"null", "none"} else s
        if _INT_STRING.fullmatch(s):
            return int(s)
        if _FLOAT_STRING.fullmatch(s):
            return float(s)
        m = _TS_STRING.fullmatch(s.replace("T", " "))
        if m:
            day, tod = m.group(1), m.group(2)
            return f"{day} {tod.split('.')[0]}" if tod else day
        return v
    if isinstance(v, (bytes, bytearray)):
        return normalize_value(v.decode("utf-8", errors="replace"))
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
    return mapping

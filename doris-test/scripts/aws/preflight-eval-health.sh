#!/usr/bin/env bash
# Lightweight pre-benchmark gate: Doris FE MySQL reachable + sample schema row counts.
# Prefer running from laptop via tunnel (9031) or on analytics host (9030).
# Do NOT run gold PG checks from nl2sql under default SG (db:5432 blocked).
set -euo pipefail

export PRED_DSN="${PRED_DSN:-mysql://root@127.0.0.1:9031/bird_minidev_olap}"
export GOLD_DSN="${GOLD_DSN:-}"
export SCHEMAS="${SCHEMAS:-california_schools,financial,formula_1}"
export MIN_ROWS="${MIN_ROWS:-1}"

PY=python3
command -v python3 >/dev/null 2>&1 || PY=python

$PY - <<'PY'
import os
import sys
from urllib.parse import urlparse

pred = os.environ.get("PRED_DSN", "mysql://root@127.0.0.1:9031/bird_minidev_olap")
gold = os.environ.get("GOLD_DSN", "").strip()
schemas = [
    s.strip()
    for s in os.environ.get("SCHEMAS", "california_schools,financial,formula_1").split(",")
    if s.strip()
]
min_rows = int(os.environ.get("MIN_ROWS", "1"))


def check_mysql(dsn: str) -> None:
    import pymysql

    p = urlparse(dsn)
    conn = pymysql.connect(
        host=p.hostname or "127.0.0.1",
        port=p.port or 3306,
        user=p.username or "root",
        password=p.password or "",
        database=(p.path or "/").lstrip("/") or None,
        connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
            print(f"DORIS_OK host={p.hostname}:{p.port}")
            for sch in schemas:
                cur.execute(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_type IN ('BASE TABLE','VIEW')",
                    (sch,),
                )
                n_tables = int(cur.fetchone()[0])
                if n_tables < 1:
                    raise SystemExit(f"SCHEMA_EMPTY schema={sch} tables=0")
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_type IN ('BASE TABLE','VIEW') "
                    "ORDER BY table_name LIMIT 1",
                    (sch,),
                )
                tbl = cur.fetchone()[0]
                # Identifiers only from information_schema; quote defensively.
                cur.execute(f"SELECT COUNT(*) FROM `{sch}`.`{tbl}`")
                cnt = int(cur.fetchone()[0])
                print(
                    f"SCHEMA_OK schema={sch} tables={n_tables} sample={sch}.{tbl} rows={cnt}"
                )
                if cnt < min_rows:
                    raise SystemExit(
                        f"SCHEMA_TOO_FEW_ROWS schema={sch} table={tbl} rows={cnt} min={min_rows}"
                    )
    finally:
        conn.close()


def check_pg(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    print("GOLD_PG_OK")


check_mysql(pred)
if gold:
    check_pg(gold)
print("PREFLIGHT_EVAL_HEALTH_OK")
PY

#!/usr/bin/env python3
"""Generate WREN_TARGET_TABLES from suite db_id list via information_schema."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg

from minidev_schemas import MINIDEV_DB_IDS

DEFAULT_CAP_PER_SCHEMA = 30


def _harness_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _db_ids_from_manifest(suite: str) -> list[str]:
    manifest = _harness_root() / "test_suites" / "minidev" / "manifests" / f"{suite}.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    questions_path = _harness_root() / "test_suites" / "minidev" / f"{suite}.json"
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    db_ids = sorted({str(r["db_id"]) for r in questions if r.get("db_id")})
    if not db_ids and data.get("question_ids"):
        raise RuntimeError(f"No db_id in suite {suite}; regenerate suite files.")
    return db_ids


def _db_ids_from_questions_file(path: Path) -> list[str]:
    questions = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(questions, list):
        raise RuntimeError(f"{path} must be a JSON array of question objects")
    db_ids = sorted({str(r["db_id"]) for r in questions if isinstance(r, dict) and r.get("db_id")})
    if not db_ids:
        raise RuntimeError(f"No db_id values found in {path}")
    return db_ids


def fetch_tables(dsn: str, schemas: list[str], cap: int) -> list[str]:
    if not schemas:
        return []
    placeholders = ",".join(["%s"] * len(schemas))
    sql = f"""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN ({placeholders})
          AND table_type = 'BASE TABLE'
        ORDER BY table_schema, table_name
    """
    out: list[str] = []
    per_schema: dict[str, int] = {}
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, schemas)
            for schema, table in cur.fetchall():
                n = per_schema.get(schema, 0)
                if cap > 0 and n >= cap:
                    continue
                out.append(f"{schema}.{table}")
                per_schema[schema] = n + 1
    return out


def resolve_pg_schemas(db_ids: list[str], *, db_profile: str) -> list[str]:
    """Map logical minidev db_id to PostgreSQL schemas (1-db uses public for formula_1)."""
    if db_profile == "1db":
        return ["public"]
    return db_ids


def resolve_db_ids(*, suite: str, questions_file: Path | None, scope: str) -> list[str]:
    if scope == "minidev":
        return list(MINIDEV_DB_IDS)
    if questions_file is not None:
        return _db_ids_from_questions_file(questions_file)
    return _db_ids_from_manifest(suite)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="smoke_3")
    parser.add_argument("--questions-file", type=Path, default=None, help="JSON array with db_id per row")
    parser.add_argument(
        "--scope",
        choices=["suite", "minidev"],
        default=os.environ.get("WREN_TABLE_SCOPE", "minidev"),
        help="suite: db_ids from suite file; minidev: all 11 BIRD minidev schemas",
    )
    parser.add_argument("--dsn", default=os.environ.get("NL2SQL_PG_DSN", "postgresql://olap:olap@127.0.0.1:55432/bird"))
    parser.add_argument(
        "--cap-per-schema",
        type=int,
        default=DEFAULT_CAP_PER_SCHEMA,
        help="Max tables per schema (0 = unlimited / all tables)",
    )
    parser.add_argument(
        "--db-profile",
        choices=["1db", "full"],
        default=os.environ.get("NL2SQL_DB_PROFILE", "full"),
        help="1db: formula_1 tables live in public; full: schema per db_id",
    )
    parser.add_argument("--print-export", action="store_true", help="Print export WREN_TARGET_TABLES=...")
    parser.add_argument("--print-schemas-export", action="store_true", help="Print export WREN_TARGET_SCHEMAS=...")
    args = parser.parse_args()

    db_ids = resolve_db_ids(suite=args.suite, questions_file=args.questions_file, scope=args.scope)
    schemas = resolve_pg_schemas(db_ids, db_profile=args.db_profile)
    if args.print_schemas_export:
        print(f"WREN_TARGET_SCHEMAS={','.join(schemas)}")
        return 0

    tables = fetch_tables(args.dsn, schemas, args.cap_per_schema)
    if not tables and args.db_profile == "full":
        print(
            f"WARN: no tables found for schemas {schemas}; load full BIRD (load_bird_dev.ps1) before Wren deploy",
            file=sys.stderr,
        )
    value = ",".join(tables)
    if args.print_export:
        print(f"WREN_TARGET_TABLES={value}")
    else:
        print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

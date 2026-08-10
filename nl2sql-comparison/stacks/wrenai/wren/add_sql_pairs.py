"""Register WrenAI question/SQL pairs via GraphQL (Knowledge -> SQL pairs)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

WREN_UI_URL = os.environ.get("WREN_UI_URL", "http://127.0.0.1:3001").rstrip("/")
GRAPHQL_URL = f"{WREN_UI_URL}/api/graphql"


def gql(query: str, variables: dict[str, Any] | None = None, timeout: int = 120) -> dict[str, Any]:
    response = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": variables or {}},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], indent=2))
    return payload["data"]


def wait_for_ui(timeout_seconds: int = 300) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            gql("query { __typename }", timeout=10)
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError(f"Wren UI not ready at {WREN_UI_URL} after {timeout_seconds}s")


def list_sql_pairs() -> list[dict[str, Any]]:
    data = gql(
        """
        query {
          sqlPairs {
            id
            question
            sql
          }
        }
        """
    )
    rows = data.get("sqlPairs") or []
    return [r for r in rows if isinstance(r, dict)]


def create_sql_pair(question: str, sql: str, *, timeout: int = 300) -> dict[str, Any]:
    data = gql(
        """
        mutation($data: CreateSqlPairInput!) {
          createSqlPair(data: $data) {
            id
            question
            sql
          }
        }
        """,
        {"data": {"question": question.strip(), "sql": sql.strip()}},
        timeout=timeout,
    )
    row = data.get("createSqlPair")
    if not row:
        raise RuntimeError(f"createSqlPair returned empty payload for question={question!r}")
    return row


def _normalize_key(question: str, sql: str) -> tuple[str, str]:
    return (question.strip().lower(), " ".join(sql.split()).lower())


def load_pairs_file(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a JSON array of {{question, sql}} objects")
    pairs: list[dict[str, str]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{path}[{i}] must be an object")
        question = str(item.get("question", "")).strip()
        sql = str(item.get("sql", "")).strip()
        if not question or not sql:
            raise ValueError(f"{path}[{i}] requires non-empty question and sql")
        pairs.append({"question": question, "sql": sql})
    return pairs


def sync_sql_pairs(
    pairs: list[dict[str, str]],
    *,
    skip_existing: bool = True,
    pair_timeout: int = 300,
) -> list[dict[str, Any]]:
    existing_keys: set[tuple[str, str]] = set()
    if skip_existing:
        for row in list_sql_pairs():
            existing_keys.add(_normalize_key(str(row.get("question", "")), str(row.get("sql", ""))))

    created: list[dict[str, Any]] = []
    for pair in pairs:
        key = _normalize_key(pair["question"], pair["sql"])
        if skip_existing and key in existing_keys:
            print(f"skip existing: {pair['question'][:80]!r}")
            continue
        row = create_sql_pair(pair["question"], pair["sql"], timeout=pair_timeout)
        created.append(row)
        existing_keys.add(key)
        print(f"created id={row.get('id')}: {pair['question'][:80]!r}")
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add WrenAI question/SQL knowledge pairs")
    parser.add_argument("--pairs-file", type=Path, default=None, help="JSON file with [{question, sql}, ...]")
    parser.add_argument("--question", help="Natural language question for a single pair")
    parser.add_argument("--sql", help="SQL for a single pair")
    parser.add_argument("--list", action="store_true", help="List existing pairs and exit")
    parser.add_argument("--no-skip-existing", action="store_true", help="Create even if an identical pair exists")
    parser.add_argument("--ui-wait-sec", type=int, default=int(os.environ.get("WREN_UI_WAIT_SEC", "300")))
    parser.add_argument("--pair-timeout-sec", type=int, default=int(os.environ.get("WREN_SQL_PAIR_TIMEOUT_SEC", "300")))
    args = parser.parse_args(argv)

    wait_for_ui(timeout_seconds=args.ui_wait_sec)

    if args.list:
        rows = list_sql_pairs()
        print(json.dumps(rows, indent=2))
        return 0

    pairs: list[dict[str, str]] = []
    if args.pairs_file:
        pairs.extend(load_pairs_file(args.pairs_file))
    elif os.environ.get("WREN_SQL_PAIRS_FILE"):
        pairs.extend(load_pairs_file(Path(os.environ["WREN_SQL_PAIRS_FILE"])))

    if args.question and args.sql:
        pairs.append({"question": args.question, "sql": args.sql})

    if not pairs:
        parser.error("Provide --question and --sql, --pairs-file, or WREN_SQL_PAIRS_FILE")

    created = sync_sql_pairs(
        pairs,
        skip_existing=not args.no_skip_existing,
        pair_timeout=args.pair_timeout_sec,
    )
    print(f"Done. Created {len(created)} pair(s); total listed now: {len(list_sql_pairs())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

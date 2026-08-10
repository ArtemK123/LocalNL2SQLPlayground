"""
Register OLAP PostgreSQL connections in Chat2DB via its REST API.

Designed to run inside the compose `chat2db-seed` service (profile `bootstrap`)
or manually after the stack is up:

  docker compose --profile bootstrap run --rm chat2db-seed

Requires default admin user (see CHAT2DB_USER / CHAT2DB_PASSWORD).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import requests

BASE = os.environ.get("CHAT2DB_URL", "http://127.0.0.1:10825").rstrip("/")
USER = os.environ.get("CHAT2DB_USER", "chat2db")
PASSWORD = os.environ.get("CHAT2DB_PASSWORD", "chat2db")

PG_HOST = os.environ.get("OLAP_PG_HOST", "olap-postgres")
PG_PORT = os.environ.get("OLAP_PG_PORT", "5432")
PG_DB = os.environ.get("OLAP_PG_DATABASE", "olap")
OWNER_USER = os.environ.get("OLAP_PG_OWNER_USER", "olap")
OWNER_PASSWORD = os.environ.get("OLAP_PG_OWNER_PASSWORD", "olap")
RO_USER = os.environ.get("NL2SQL_RO_USER", "nl2sql_ro")
RO_PASSWORD = os.environ.get("NL2SQL_RO_PASSWORD", "nl2sql_ro")

PG_TYPE = os.environ.get("CHAT2DB_PG_TYPE", "POSTGRESQL")
PG_TYPE_FALLBACKS = ("POSTGRESQL", "POSTGRES", "PG")
ENV_ID = int(os.environ.get("CHAT2DB_ENVIRONMENT_ID", "2"))

ALIAS_OWNER = os.environ.get("CHAT2DB_ALIAS_OWNER", "Local OLAP (owner)")
ALIAS_RO = os.environ.get("CHAT2DB_ALIAS_RO", "Local OLAP (nl2sql_ro read-only)")


def _login(session: requests.Session) -> str:
    url = f"{BASE}/api/oauth/login_a"
    resp = session.post(
        url,
        json={"userName": USER, "password": PASSWORD},
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(f"Login failed: {body}")
    token = body.get("data")
    if not token or not isinstance(token, str):
        raise RuntimeError(f"Login response missing token: {body}")
    return token


def _list_aliases(session: requests.Session, token: str) -> set[str]:
    aliases: set[str] = set()
    page = 1
    while True:
        resp = session.get(
            f"{BASE}/api/connection/datasource/list",
            params={"pageNo": page, "pageSize": 50},
            headers={"CHAT2DB": token},
            timeout=60,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        if not body.get("success"):
            raise RuntimeError(f"List datasources failed: {body}")
        data = body.get("data") or {}
        rows = data.get("data") or []
        for row in rows:
            a = row.get("alias")
            if a:
                aliases.add(str(a))
        if not data.get("hasNextPage"):
            break
        page += 1
    return aliases


def _create_ds(
    session: requests.Session,
    token: str,
    *,
    alias: str,
    pg_user: str,
    pg_password: str,
) -> None:
    jdbc = f"jdbc:postgresql://{PG_HOST}:{PG_PORT}/{PG_DB}"
    types_to_try: tuple[str, ...]
    if PG_TYPE in PG_TYPE_FALLBACKS:
        types_to_try = (PG_TYPE,) + tuple(t for t in PG_TYPE_FALLBACKS if t != PG_TYPE)
    else:
        types_to_try = (PG_TYPE,)

    last_body: dict[str, Any] | None = None
    for db_type in types_to_try:
        payload = {
            "alias": alias,
            "url": jdbc,
            "user": pg_user,
            "password": pg_password,
            "authenticationType": "1",
            "type": db_type,
            "host": PG_HOST,
            "port": str(PG_PORT),
            "environmentId": ENV_ID,
        }
        resp = session.post(
            f"{BASE}/api/connection/datasource/create",
            json=payload,
            headers={"CHAT2DB": token, "Content-Type": "application/json"},
            timeout=60,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("success"):
            print(f"Created {alias!r} with type={db_type!r}", flush=True)
            return
        last_body = body

    raise RuntimeError(f"Create datasource failed for {alias!r}: {last_body}")


def main() -> int:
    session = requests.Session()
    print(f"Chat2DB seed: base={BASE}", flush=True)
    token = _login(session)
    existing = _list_aliases(session, token)
    print(f"Existing datasource aliases ({len(existing)}): {sorted(existing)}", flush=True)

    if ALIAS_OWNER not in existing:
        print(f"Creating datasource: {ALIAS_OWNER}", flush=True)
        _create_ds(session, token, alias=ALIAS_OWNER, pg_user=OWNER_USER, pg_password=OWNER_PASSWORD)
    else:
        print(f"Skip (exists): {ALIAS_OWNER}", flush=True)

    if ALIAS_RO not in existing:
        print(f"Creating datasource: {ALIAS_RO}", flush=True)
        _create_ds(session, token, alias=ALIAS_RO, pg_user=RO_USER, pg_password=RO_PASSWORD)
    else:
        print(f"Skip (exists): {ALIAS_RO}", flush=True)

    print("Seed complete.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except requests.RequestException as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)

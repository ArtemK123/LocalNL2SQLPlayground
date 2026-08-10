from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

WREN_UI_URL = os.environ.get("WREN_UI_URL", "http://127.0.0.1:3001").rstrip("/")
GRAPHQL_URL = f"{WREN_UI_URL}/api/graphql"

TARGET_TABLES_RAW = os.environ.get("WREN_TARGET_TABLES", "*")
SELECT_ALL_TABLES = TARGET_TABLES_RAW.strip().lower() in {"*", "all"}
TARGET_TABLES = (
    []
    if SELECT_ALL_TABLES
    else [t.strip() for t in TARGET_TABLES_RAW.split(",") if t.strip()]
)
TARGET_SCHEMAS_RAW = os.environ.get("WREN_TARGET_SCHEMAS", "").strip()
TARGET_SCHEMAS = {s.strip().lower() for s in TARGET_SCHEMAS_RAW.split(",") if s.strip()}
RESYNC_MODEL = os.environ.get("WREN_RESYNC_MODEL", "").strip().lower() in {"1", "true", "yes"}


def gql(query: str, variables: dict[str, Any] | None = None, timeout: int = 60) -> dict[str, Any]:
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


def wait_for_ui() -> None:
    for _ in range(180):
        try:
            gql("query { __typename }", timeout=10)
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("Wren UI is not ready in time")


def get_onboarding_status() -> str:
    data = gql("query { onboardingStatus { status } }", timeout=20)
    return str((data.get("onboardingStatus") or {}).get("status") or "NOT_STARTED")


def ensure_project_exists() -> None:
    # Wait until Wren UI GraphQL is ready (onboarding query always succeeds).
    for _ in range(120):
        try:
            get_onboarding_status()
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("Wren onboarding endpoint is not available after retries")


def _save_datasource() -> None:
    mutation = """
    mutation($type: DataSourceName!, $properties: JSON!) {
      saveDataSource(data: { type: $type, properties: $properties }) {
        type
      }
    }
    """
    connection_variants = [
        {
            "host": os.environ.get("WREN_DB_HOST", "olap-postgres"),
            "port": int(os.environ.get("WREN_DB_PORT", "5432")),
            "database": os.environ.get("WREN_DB_DATABASE", "olap"),
            "username": os.environ.get("WREN_DB_USERNAME", "nl2sql_ro"),
            "password": os.environ.get("WREN_DB_PASSWORD", "nl2sql_ro"),
            "ssl": False,
        },
        {
            "host": os.environ.get("WREN_DB_HOST", "olap-postgres"),
            "port": int(os.environ.get("WREN_DB_PORT", "5432")),
            "database": os.environ.get("WREN_DB_DATABASE", "olap"),
            "user": os.environ.get("WREN_DB_USERNAME", "nl2sql_ro"),
            "password": os.environ.get("WREN_DB_PASSWORD", "nl2sql_ro"),
            "ssl": False,
        },
        {
            "host": os.environ.get("WREN_DB_HOST", "olap-postgres"),
            "port": str(os.environ.get("WREN_DB_PORT", "5432")),
            "dbname": os.environ.get("WREN_DB_DATABASE", "olap"),
            "username": os.environ.get("WREN_DB_USERNAME", "nl2sql_ro"),
            "password": os.environ.get("WREN_DB_PASSWORD", "nl2sql_ro"),
            "ssl": False,
        },
    ]
    last_error: Exception | None = None
    for props in connection_variants:
        try:
            gql(
                mutation,
                {
                    "type": os.environ.get("WREN_DATASOURCE_TYPE", "POSTGRES"),
                    "properties": props,
                },
            )
            return
        except Exception as exc:  # pragma: no cover - best effort fallback
            last_error = exc
    if last_error:
        raise last_error


def _list_tables() -> list[str]:
    data = gql("query { listDataSourceTables { name } }")
    rows = data.get("listDataSourceTables", []) or []
    tables: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if name:
            tables.append(str(name))
    return sorted(set(tables))


def _table_schema_key(name: str) -> str:
    """Best-effort schema prefix from Wren/Postgres table identifiers."""
    lower = name.lower()
    if "." in lower:
        return lower.split(".", 1)[0]
    for sep in ("_",):
        if sep in lower:
            return lower.split(sep, 1)[0]
    return lower


def _matches_target_schema(name: str) -> bool:
    if not TARGET_SCHEMAS:
        return True
    key = _table_schema_key(name)
    return key in TARGET_SCHEMAS


def _pick_tables(discovered: list[str]) -> list[str]:
    if SELECT_ALL_TABLES:
        picked = sorted(set(discovered))
        if TARGET_SCHEMAS:
            picked = [t for t in picked if _matches_target_schema(t)]
            if not picked and discovered:
                inferred = {_table_schema_key(t) for t in discovered}
                if len(inferred) == 1:
                    pg_schema = next(iter(inferred))
                    print(
                        "WARN: WREN_TARGET_SCHEMAS did not match discovered tables; "
                        f"selecting all tables from PostgreSQL schema '{pg_schema}'."
                    )
                    return sorted(set(discovered))
        return picked
    discovered_lower = {d.lower(): d for d in discovered}
    picked: list[str] = []
    for requested in TARGET_TABLES:
        exact = discovered_lower.get(requested.lower())
        if exact:
            picked.append(exact)
            continue
        suffix = requested.split(".")[-1].lower()
        for raw in discovered:
            if raw.split(".")[-1].lower() == suffix:
                picked.append(raw)
                break
    if picked:
        return sorted(set(picked))
    fallback = discovered[:6]
    if TARGET_SCHEMAS:
        fallback = [t for t in discovered if _matches_target_schema(t)]
    return fallback


def _save_tables(tables: list[str]) -> None:
    gql(
        """
        mutation($tables: [String!]!) {
          saveTables(data: { tables: $tables })
        }
        """,
        {"tables": tables},
    )


def _deploy() -> None:
    gql("mutation { deploy(force: true) }")


def _wait_for_model_sync(timeout_s: int = 900) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        data = gql("query { modelSync { status } }", timeout=30)
        status = str((data.get("modelSync") or {}).get("status") or "")
        if status in {"SYNCHRONIZED", "FINISHED"}:
            print(f"Wren modelSync={status}")
            return
        time.sleep(5)
    raise RuntimeError("Wren modelSync did not finish in time")


def _ensure_datasource() -> None:
    status = get_onboarding_status()
    if status in {"DATASOURCE_SAVED", "ONBOARDING_FINISHED", "WITH_SAMPLE_DATASET"}:
        print(f"Wren datasource already configured (onboarding={status}).")
        return
    for _ in range(60):
        try:
            _save_datasource()
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("Unable to save datasource in Wren after retries")


def main() -> int:
    wait_for_ui()
    ensure_project_exists()

    status = get_onboarding_status()
    if status == "ONBOARDING_FINISHED":
        if RESYNC_MODEL:
            print("Wren bootstrap: explicit resync requested (WREN_RESYNC_MODEL=true).")
            discovered = _list_tables()
            if not discovered:
                raise RuntimeError("No tables discovered from datasource in Wren")
            selected = _pick_tables(discovered)
            if not selected:
                scope = f" schemas={sorted(TARGET_SCHEMAS)}" if TARGET_SCHEMAS else ""
                raise RuntimeError(
                    f"No tables selected for Wren resync (discovered={len(discovered)}{scope})."
                )
            _save_tables(selected)
            _deploy()
            _wait_for_model_sync()
            print(
                f"Wren model resync complete. Selected {len(selected)} tables "
                f"(discovered={len(discovered)})."
            )
        else:
            print("Wren bootstrap skipped: onboarding finished (set WREN_RESYNC_MODEL=true to re-index).")
        return 0

    _ensure_datasource()
    gql("mutation { triggerDataSourceDetection }")

    discovered: list[str] = []
    for _ in range(30):
        discovered = _list_tables()
        if discovered:
            break
        time.sleep(2)
    if not discovered:
        raise RuntimeError("No tables discovered from datasource in Wren")

    selected = _pick_tables(discovered)
    if not selected:
        scope = f" schemas={sorted(TARGET_SCHEMAS)}" if TARGET_SCHEMAS else ""
        raise RuntimeError(
            f"No tables selected for Wren project (discovered={len(discovered)}{scope}). "
            "Load full BIRD_dev (per-db_id schemas) and set WREN_TARGET_SCHEMAS to minidev db_ids, "
            "or use WREN_TARGET_SCHEMAS=public for 1-db / public-schema layouts."
        )
    _save_tables(selected)
    _deploy()
    _wait_for_model_sync()
    print(f"Wren bootstrap complete. Selected {len(selected)} tables (discovered={len(discovered)}).")
    if len(selected) <= 40:
        print(f"Selected tables: {selected}")
    else:
        print(f"Selected tables sample: {selected[:20]} ...")

    # Optional manual SQL pairs (do not seed benchmark questions — that bypasses generation).
    pairs_file = os.environ.get("WREN_SQL_PAIRS_FILE", "").strip()
    if pairs_file and Path(pairs_file).is_file():
        from add_sql_pairs import load_pairs_file, sync_sql_pairs

        created = sync_sql_pairs(load_pairs_file(Path(pairs_file)))
        print(f"Wren SQL pairs synced from {pairs_file}: created {len(created)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

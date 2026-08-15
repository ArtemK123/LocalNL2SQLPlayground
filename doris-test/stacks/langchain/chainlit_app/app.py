from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import chainlit as cl
import requests
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

LANGCHAIN_API_URL = os.environ.get("LANGCHAIN_API_URL", "http://localhost:8011").rstrip("/")
CHAINLIT_USERNAME = os.environ.get("CHAINLIT_USERNAME", "admin")
CHAINLIT_PASSWORD = os.environ.get("CHAINLIT_PASSWORD", "admin")
HISTORY_DB_PATH = Path(os.environ.get("CHAINLIT_HISTORY_DB_PATH", "/app/.chainlit/history.db"))

# Columns required by chainlit>=2 SQLAlchemyDataLayer (see chainlit/data/storage_clients/sql_alchemy.py).
_STEPS_COLUMNS = (
    '"autoCollapse" INTEGER',
    '"defaultOpen" INTEGER',
    '"showInput" TEXT',
)


def _migrate_legacy_chainlit_schema(conn: sqlite3.Connection) -> None:
    """Drop outdated custom tables so Chainlit recreates a compatible schema."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='steps'"
    ).fetchone()
    if not row:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(steps)").fetchall()}
    if "autoCollapse" in cols:
        return
    for tbl in ("feedbacks", "elements", "steps", "threads"):
        conn.execute(f"DROP TABLE IF EXISTS {tbl}")


def _init_history_db() -> None:
    HISTORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(HISTORY_DB_PATH) as conn:
        _migrate_legacy_chainlit_schema(conn)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                identifier TEXT NOT NULL UNIQUE,
                metadata TEXT NOT NULL,
                "createdAt" TEXT
            );
            """
        )
        # Only ensure users here; SQLAlchemyDataLayer creates steps/threads/elements/feedbacks.
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='steps'"
        ).fetchone()
        if row:
            existing = {r[1] for r in conn.execute("PRAGMA table_info(steps)").fetchall()}
            for col_def in _STEPS_COLUMNS:
                col_name = col_def.split()[0].strip('"')
                if col_name not in existing:
                    conn.execute(f"ALTER TABLE steps ADD COLUMN {col_def}")


@cl.data_layer
def get_data_layer() -> SQLAlchemyDataLayer:
    _init_history_db()
    return SQLAlchemyDataLayer(conninfo=f"sqlite+aiosqlite:///{HISTORY_DB_PATH.as_posix()}")


@cl.password_auth_callback
def auth_callback(username: str, password: str) -> cl.User | None:
    if username == CHAINLIT_USERNAME and password == CHAINLIT_PASSWORD:
        return cl.User(
            identifier=username,
            metadata={"provider": "credentials", "role": "user"},
        )
    return None


@cl.on_chat_start
async def on_chat_start() -> None:
    user = cl.user_session.get("user")
    user_label = user.identifier if user else "user"
    await cl.Message(
        content=(
            f"Local NL2SQL assistant is ready, {user_label}.\n"
            "Ask business questions about OLAP data (analytics/mart schemas)."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    request_started = time.perf_counter()
    user_question = message.content.strip()
    if not user_question:
        await cl.Message(content="Please enter a question.").send()
        return

    try:
        response = requests.post(
            f"{LANGCHAIN_API_URL}/v1/chat",
            json={"question": user_question},
            timeout=600,
        )
        api_roundtrip_ms = int((time.perf_counter() - request_started) * 1000)
    except requests.RequestException as exc:
        await cl.Message(content=f"API connection failed: {exc}").send()
        return

    if response.status_code >= 400:
        await cl.Message(content=f"API error ({response.status_code}): {response.text}").send()
        return

    payload = response.json()
    rows = payload.get("rows", [])
    preview = rows[:20]
    answer = payload.get("answer", "")
    sql = payload.get("sql", "")
    model_used = payload.get("model_used", "unknown")
    execution_ms = payload.get("execution_ms", 0)
    total_ms = payload.get("total_ms", 0)
    reasoning_summary = payload.get("reasoning_summary", "")
    ui_total_ms = int((time.perf_counter() - request_started) * 1000)

    text = (
        f"{answer}\n\n"
        f"Model: `{model_used}`\n"
        f"DB execution: `{execution_ms} ms`\n"
        f"API total: `{total_ms} ms`\n"
        f"HTTP round-trip: `{api_roundtrip_ms} ms`\n"
        f"End-to-end (send -> answer rendered): `{ui_total_ms} ms`\n\n"
        f"Reasoning trace:\n{reasoning_summary}\n\n"
        f"```sql\n{sql}\n```\n\n"
        f"Result preview:\n```json\n{json.dumps(preview, default=str, indent=2)}\n```"
    )

    await cl.Message(content=text).send()

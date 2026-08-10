from __future__ import annotations

import asyncio
import json
import os
import time

import chainlit as cl
import requests
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

from db_schema import HISTORY_DB_PATH, init_history_db

LANGCHAIN_API_URL = os.environ.get("LANGCHAIN_API_URL", "http://localhost:8011").rstrip("/")
CHAINLIT_USERNAME = os.environ.get("CHAINLIT_USERNAME", "admin")
CHAINLIT_PASSWORD = os.environ.get("CHAINLIT_PASSWORD", "admin")
API_TIMEOUT_SEC = float(os.environ.get("CHAINLIT_API_TIMEOUT_SEC", "600"))


@cl.data_layer
def get_data_layer() -> SQLAlchemyDataLayer:
    init_history_db()
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


def _call_langchain_api(question: str) -> requests.Response:
    return requests.post(
        f"{LANGCHAIN_API_URL}/v1/chat",
        json={"question": question},
        timeout=API_TIMEOUT_SEC,
    )


@cl.on_message
async def on_message(message: cl.Message) -> None:
    request_started = time.perf_counter()
    user_question = message.content.strip()
    if not user_question:
        await cl.Message(content="Please enter a question.").send()
        return

    progress = cl.Message(content="Generating SQL and running the query…")
    await progress.send()

    try:
        response = await asyncio.to_thread(_call_langchain_api, user_question)
        api_roundtrip_ms = int((time.perf_counter() - request_started) * 1000)
    except requests.Timeout as exc:
        await progress.remove()
        await cl.Message(
            content=(
                f"API timed out after {int(API_TIMEOUT_SEC)}s. "
                f"The backend may still be processing on {LANGCHAIN_API_URL}. ({exc})"
            )
        ).send()
        return
    except requests.RequestException as exc:
        await progress.remove()
        await cl.Message(content=f"API connection failed: {exc}").send()
        return

    await progress.remove()

    if response.status_code >= 400:
        detail = response.text
        try:
            detail = response.json().get("detail", detail)
        except Exception:
            pass
        await cl.Message(content=f"API error ({response.status_code}): {detail}").send()
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

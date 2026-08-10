"""Streamlit entrypoint: patch Django API URL in-process, then load PremSQL Playground.

Must be started with: streamlit run run_playground_ui.py
(Do not subprocess streamlit — the child would reset BASE_URL to 127.0.0.1:8000.)
"""
from __future__ import annotations

import os

import premsql.playground.backend.backend_client as backend_client


def _backend_api_url() -> str:
    url = os.environ.get(
        "PREMSQL_BACKEND_API_URL", "http://premsql-playground-api:8000/api"
    ).rstrip("/")
    if not url.endswith("/api"):
        url = f"{url}/api"
    return url


backend_client.BASE_URL = _backend_api_url()

from patch_playground_chat import apply_playground_chat_patches

apply_playground_chat_patches()

from premsql.playground.frontend.main import main

main()

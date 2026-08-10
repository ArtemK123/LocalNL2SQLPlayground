"""Debug-only HTTP health probes — never used for scored benchmark runs."""

from __future__ import annotations

import urllib.request
from typing import Optional


def probe_url(url: str, *, timeout_s: float = 5.0) -> tuple[bool, Optional[str]]:
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            return 200 <= resp.status < 400, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


FRAMEWORK_DEBUG_URLS = {
    "langchain": "http://127.0.0.1:8011/healthz",
    "dbgpt": "http://127.0.0.1:8012/healthz",
    "premsql": "http://127.0.0.1:8010/health",
    "vanna": "http://127.0.0.1:8001/docs",
    "wrenai": "http://127.0.0.1:3001",
    "chat2db": "http://127.0.0.1:10825",
}

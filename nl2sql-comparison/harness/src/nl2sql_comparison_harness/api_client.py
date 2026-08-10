from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib import error, request

from nl2sql_comparison_harness.ui.drivers import normalize_framework

FRAMEWORK_API_CHAT_URLS: dict[str, str] = {
    "langchain": "http://127.0.0.1:8011/v1/chat",
    "dbgpt": "http://127.0.0.1:8012/v1/chat",
}

API_FRAMEWORKS = frozenset(FRAMEWORK_API_CHAT_URLS.keys())

_SQL_IN_ERROR_RE = re.compile(r"\[SQL:\s*(.+?)\]\s*(?:\[parameters:|$)", re.DOTALL)


def sql_from_api_error_detail(detail: str) -> Optional[str]:
    """Extract generated SQL from langchain-api HTTP 400 execution error bodies."""
    if not detail:
        return None
    m = _SQL_IN_ERROR_RE.search(detail)
    if not m:
        return None
    sql = m.group(1).strip()
    # Drop SELECT * FROM (...) AS q LIMIT ... wrappers / unbound %(max_rows)s.
    from nl2sql_comparison_harness.db import strip_exec_wrapper

    sql = strip_exec_wrapper(sql)
    return sql if sql.upper().startswith(("SELECT", "WITH")) else None


@dataclass
class ApiAskResult:
    pred_sql: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


def default_api_url(framework: str) -> str:
    fw = normalize_framework(framework)
    if fw not in FRAMEWORK_API_CHAT_URLS:
        raise ValueError(f"No default API URL for framework '{fw}' (supported: {sorted(API_FRAMEWORKS)})")
    return FRAMEWORK_API_CHAT_URLS[fw]


def ask_via_api(
    *,
    api_url: str,
    question: str,
    timeout_s: float,
    db_id: str | None = None,
    evidence: str | None = None,
) -> ApiAskResult:
    payload: dict[str, str] = {"question": question}
    if db_id:
        payload["db_id"] = db_id
    if evidence:
        payload["evidence"] = evidence
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        api_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        detail = raw[:2000]
        latency_ms = int((time.perf_counter() - started) * 1000)
        parsed_detail = detail
        try:
            parsed_detail = json.loads(raw).get("detail", detail)
        except json.JSONDecodeError:
            pass
        salvaged = sql_from_api_error_detail(str(parsed_detail))
        if salvaged:
            return ApiAskResult(
                pred_sql=salvaged,
                latency_ms=latency_ms,
                error="http_error_sql_salvaged",
                raw={"http_status": exc.code, "detail": parsed_detail},
            )
        return ApiAskResult(
            error=f"HTTP {exc.code}: {detail[:500]}",
            latency_ms=latency_ms,
        )
    except Exception as exc:  # noqa: BLE001
        return ApiAskResult(
            error=str(exc),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    latency_ms = int(payload.get("total_ms") or (time.perf_counter() - started) * 1000)
    sql = (payload.get("sql") or "").strip()
    if not sql:
        return ApiAskResult(
            error="empty_sql",
            latency_ms=latency_ms,
            raw=payload if isinstance(payload, dict) else {},
        )
    return ApiAskResult(pred_sql=sql, latency_ms=latency_ms, raw=payload if isinstance(payload, dict) else {})

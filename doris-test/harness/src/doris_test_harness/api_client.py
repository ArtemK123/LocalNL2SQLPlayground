from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib import error, request

_SQL_IN_ERROR_RE = re.compile(r"\[SQL:\s*(.+?)\]\s*(?:\[parameters:|$)", re.DOTALL)


def sql_from_api_error_detail(detail: str) -> Optional[str]:
    if not detail:
        return None
    m = _SQL_IN_ERROR_RE.search(detail)
    if not m:
        return None
    sql = m.group(1).strip().rstrip(";")
    return sql if sql.upper().startswith(("SELECT", "WITH")) else None


@dataclass
class ApiAskResult:
    pred_sql: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


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
            payload_out = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        latency_ms = int((time.perf_counter() - started) * 1000)
        detail = raw[:2000]
        try:
            detail = json.loads(raw).get("detail", detail)
        except json.JSONDecodeError:
            pass
        salvaged = sql_from_api_error_detail(str(detail))
        if salvaged:
            return ApiAskResult(
                pred_sql=salvaged,
                latency_ms=latency_ms,
                error="http_error_sql_salvaged",
                raw={"http_status": exc.code, "detail": detail},
            )
        return ApiAskResult(
            error=f"http_{exc.code}",
            latency_ms=latency_ms,
            raw={"detail": str(detail)[:2000]},
        )
    except Exception as exc:  # noqa: BLE001
        return ApiAskResult(
            error=str(exc),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    latency_ms = int(payload_out.get("total_ms") or (time.perf_counter() - started) * 1000)
    sql = (payload_out.get("sql") or payload_out.get("pred_sql") or "").strip()
    if not sql:
        return ApiAskResult(error="empty_sql", latency_ms=latency_ms, raw=payload_out)
    return ApiAskResult(pred_sql=sql, latency_ms=latency_ms, raw=payload_out)

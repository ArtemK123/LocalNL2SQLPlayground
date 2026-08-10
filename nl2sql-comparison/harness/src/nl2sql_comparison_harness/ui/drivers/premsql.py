from __future__ import annotations

import json
import re
import time

from nl2sql_comparison_harness.ui.sql_extract import normalize_sql_candidate
from nl2sql_comparison_harness.ui.drivers.base import UIAskResult


class PremsqlDriver:
    """PremSQL AgentServer exposes REST only; use bundled Swagger UI at /docs."""

    def __init__(self, page, ui_url: str) -> None:
        self.page = page
        self.ui_url = ui_url.rstrip("/")
        self.docs_url = f"{self.ui_url}/docs"

    def ensure_ready(self) -> None:
        self.page.goto(self.docs_url, wait_until="domcontentloaded", timeout=120_000)
        self.page.get_by_text("POST", exact=True).first.wait_for(state="visible", timeout=60_000)
        completion = self.page.get_by_text("/completion", exact=False)
        completion.first.wait_for(state="visible", timeout=30_000)

    def ask(self, question: str, *, timeout_s: float) -> UIAskResult:
        t0 = time.perf_counter()
        try:
            row = self.page.get_by_role("button", name="/completion")
            if row.count() == 0:
                row = self.page.locator("span").filter(has_text="/completion")
            row.first.click()
            try_it = self.page.get_by_role("button", name="Try it out")
            if try_it.count() > 0:
                try_it.first.click()
            body_area = self.page.locator("textarea").filter(has_text="").last
            if body_area.count() == 0:
                body_area = self.page.locator("textarea").last
            payload = json.dumps({"question": question})
            body_area.fill(payload, timeout=10_000)
            execute = self.page.get_by_role("button", name="Execute")
            execute.first.click()
            deadline = time.monotonic() + timeout_s
            response_text = ""
            while time.monotonic() < deadline:
                blocks = self.page.locator(".responses-wrapper pre, .response pre, pre.microlight")
                if blocks.count() > 0:
                    response_text = blocks.last.inner_text()
                    if "message" in response_text or "sql" in response_text.lower():
                        break
                self.page.wait_for_timeout(500)
            pred = None
            if response_text:
                try:
                    data = json.loads(response_text)
                    msg = data.get("message") or data
                    for key in ("sql", "generated_sql", "query"):
                        if isinstance(msg, dict) and msg.get(key):
                            pred = str(msg[key]).strip()
                            break
                    if not pred and isinstance(msg, dict):
                        text = json.dumps(msg)
                        pred = normalize_sql_candidate(text)
                except json.JSONDecodeError:
                    pred = normalize_sql_candidate(response_text)
            if not pred:
                pred = normalize_sql_candidate(response_text)
            if not pred:
                return UIAskResult(
                    pred_sql=None,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    error="No SQL found in PremSQL /completion response",
                )
            return UIAskResult(pred_sql=pred, latency_ms=int((time.perf_counter() - t0) * 1000))
        except Exception as exc:  # noqa: BLE001
            return UIAskResult(
                pred_sql=None,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                error=str(exc),
            )

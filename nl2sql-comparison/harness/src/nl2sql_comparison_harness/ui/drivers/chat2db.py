from __future__ import annotations

import time

from nl2sql_comparison_harness.ui.drivers._helpers import fill_chat_and_submit, wait_for_sql_in_text
from nl2sql_comparison_harness.ui.drivers.base import UIAskResult


class Chat2dbDriver:
    def __init__(self, page, ui_url: str) -> None:
        self.page = page
        self.ui_url = ui_url.rstrip("/")

    def ensure_ready(self) -> None:
        self.page.goto(self.ui_url, wait_until="domcontentloaded", timeout=120_000)
        self.page.wait_for_load_state("networkidle", timeout=120_000)

    def ask(self, question: str, *, timeout_s: float) -> UIAskResult:
        t0 = time.perf_counter()
        baseline = self.page.locator("body").inner_text()
        try:
            ai_tab = self.page.get_by_text("AI", exact=False)
            if ai_tab.count() > 0:
                ai_tab.first.click()
            fill_chat_and_submit(self.page, question)
            pred, _ = wait_for_sql_in_text(
                lambda: self.page.locator("body").inner_text(),
                timeout_s=timeout_s,
                baseline=baseline,
            )
            if not pred:
                return UIAskResult(
                    pred_sql=None,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    error="No SQL found in Chat2DB response",
                )
            return UIAskResult(pred_sql=pred, latency_ms=int((time.perf_counter() - t0) * 1000))
        except Exception as exc:  # noqa: BLE001
            return UIAskResult(
                pred_sql=None,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                error=str(exc),
            )

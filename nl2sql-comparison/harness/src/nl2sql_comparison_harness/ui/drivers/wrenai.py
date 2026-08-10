from __future__ import annotations

import re
import time

from nl2sql_comparison_harness.ui.drivers._helpers import fill_chat_and_submit, wait_for_sql_in_text
from nl2sql_comparison_harness.ui.drivers.base import UIAskResult


class WrenaiDriver:
    def __init__(self, page, ui_url: str) -> None:
        self.page = page
        self.ui_url = ui_url.rstrip("/")

    def _dismiss_onboarding(self) -> None:
        for label in ("Skip", "Got it", "Close", "Done", "Next"):
            btn = self.page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count() > 0:
                try:
                    btn.first.click(timeout=3000)
                    self.page.wait_for_timeout(500)
                except Exception:
                    pass
        try:
            self.page.locator(".driver-popover-close-btn, .driver-close-btn").first.click(timeout=2000)
        except Exception:
            pass

    def ensure_ready(self) -> None:
        self.page.goto(f"{self.ui_url}/home", wait_until="domcontentloaded", timeout=120_000)
        self.page.wait_for_load_state("networkidle", timeout=120_000)
        self._dismiss_onboarding()
        self.page.locator("textarea:visible").first.wait_for(state="visible", timeout=60_000)

    def ask(self, question: str, *, timeout_s: float) -> UIAskResult:
        t0 = time.perf_counter()
        baseline = self.page.locator("body").inner_text()
        try:
            self._dismiss_onboarding()
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
                    error="No SQL found in WrenAI response",
                )
            return UIAskResult(pred_sql=pred, latency_ms=int((time.perf_counter() - t0) * 1000))
        except Exception as exc:  # noqa: BLE001
            return UIAskResult(
                pred_sql=None,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                error=str(exc),
            )

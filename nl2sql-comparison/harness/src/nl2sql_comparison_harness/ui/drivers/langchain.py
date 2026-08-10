from __future__ import annotations

import os
import time

from nl2sql_comparison_harness.ui.drivers._helpers import fill_chat_and_submit, wait_for_sql_in_text
from nl2sql_comparison_harness.ui.drivers.base import UIAskResult


class LangchainDriver:
    def __init__(self, page, ui_url: str) -> None:
        self.page = page
        self.ui_url = ui_url.rstrip("/")
        self.username = os.environ.get("CHAINLIT_USERNAME", "admin")
        self.password = os.environ.get("CHAINLIT_PASSWORD", "admin")

    def _login_if_needed(self) -> None:
        pw = self.page.locator('input[type="password"]').first
        try:
            pw.wait_for(state="visible", timeout=20_000)
        except Exception:
            return
        user = self.page.locator(
            'input[name="username"], input#username, input[autocomplete="username"], '
            'input:not([type="password"]):not([type="hidden"])'
        ).first
        user.fill(self.username, timeout=15_000)
        pw.fill(self.password)
        self.page.locator(
            'button[type="submit"], button:has-text("Sign in"), button:has-text("Log in")'
        ).first.click()
        pw.wait_for(state="hidden", timeout=60_000)

    def ensure_ready(self) -> None:
        last_err: Exception | None = None
        for _ in range(12):
            try:
                self.page.goto(self.ui_url, wait_until="domcontentloaded", timeout=60_000)
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(5)
        if last_err is not None:
            raise last_err
        self._login_if_needed()
        self.page.locator("textarea:visible").first.wait_for(state="visible", timeout=60_000)

    def ask(self, question: str, *, timeout_s: float) -> UIAskResult:
        t0 = time.perf_counter()

        def _response_text() -> str:
            for sel in (
                "[data-step-type='assistant_message']",
                "[data-testid='assistant-message']",
                ".ai-message",
                ".step-assistant",
            ):
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    return loc.last.inner_text()
            blocks = self.page.locator("pre, code, .language-sql")
            if blocks.count() > 0:
                return blocks.last.inner_text()
            return self.page.locator("body").inner_text()

        baseline = _response_text()
        try:
            fill_chat_and_submit(self.page, question)
            try:
                self.page.wait_for_function(
                    """() => {
                      const t = document.body ? document.body.innerText : '';
                      return t.includes('```sql') || t.includes('Model:') || /\\bFROM\\b/i.test(t);
                    }""",
                    timeout=int(timeout_s * 1000),
                )
            except Exception:
                pass
            pred, _ = wait_for_sql_in_text(
                lambda: self.page.locator("body").inner_text(),
                timeout_s=timeout_s,
                baseline=baseline,
            )
            if not pred:
                return UIAskResult(
                    pred_sql=None,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    error="No SQL found in Chainlit response",
                )
            return UIAskResult(pred_sql=pred, latency_ms=int((time.perf_counter() - t0) * 1000))
        except Exception as exc:  # noqa: BLE001
            return UIAskResult(
                pred_sql=None,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                error=str(exc),
            )

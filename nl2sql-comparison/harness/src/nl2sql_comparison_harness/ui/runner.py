from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Callable, Optional

from nl2sql_comparison_harness.ui.drivers import DRIVER_CLASSES, FRAMEWORK_URLS, normalize_framework
from nl2sql_comparison_harness.ui.drivers.base import UIAskResult
from nl2sql_comparison_harness.ui.sql_extract import normalize_sql_candidate


class UIRunnerError(RuntimeError):
    pass


def _mcp_ask(
    framework: str,
    ui_url: str,
    question: str,
    *,
    timeout_s: float,
    trace_dir: Optional[str],
) -> UIAskResult:
    cmd = os.environ.get("NL2SQL_PLAYWRIGHT_MCP_CMD", "").strip()
    if not cmd:
        raise UIRunnerError("NL2SQL_PLAYWRIGHT_MCP_CMD is not set")

    payload = {
        "framework": framework,
        "question": question,
        "timeout_s": timeout_s,
        "ui_url": ui_url,
        "trace_dir": trace_dir,
    }
    proc = subprocess.run(
        shlex.split(cmd),
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=max(timeout_s + 30.0, 60.0),
        check=False,
    )
    if proc.returncode != 0:
        return UIAskResult(
            pred_sql=None,
            latency_ms=0,
            error=f"MCP bridge failed (exit {proc.returncode}): {(proc.stderr or '').strip()}",
        )
    try:
        parsed = json.loads((proc.stdout or "").strip())
    except json.JSONDecodeError as exc:
        return UIAskResult(pred_sql=None, latency_ms=0, error=f"MCP bridge non-JSON: {exc}")
    pred = normalize_sql_candidate(str(parsed.get("pred_sql") or ""))
    err = parsed.get("error")
    if err is not None:
        err = str(err).strip() or None
    latency = int(parsed.get("latency_ms") or 0)
    raw = parsed.get("raw") if isinstance(parsed.get("raw"), dict) else {}
    return UIAskResult(pred_sql=pred, latency_ms=latency, error=err, raw=raw)


def build_ui_asker(
    *,
    framework: str,
    ui_url: Optional[str] = None,
    trace_dir: Optional[Path] = None,
    headless: bool = True,
    use_mcp: bool = False,
) -> Callable[[str, float], UIAskResult]:
    fw = normalize_framework(framework)
    url = (ui_url or FRAMEWORK_URLS[fw].default_url).rstrip("/")
    trace_path = str(trace_dir) if trace_dir else None

    if use_mcp or os.environ.get("NL2SQL_PLAYWRIGHT_MCP_CMD"):
        def ask_mcp(question: str, timeout_s: float) -> UIAskResult:
            return _mcp_ask(fw, url, question, timeout_s=timeout_s, trace_dir=trace_path)

        return ask_mcp

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise UIRunnerError(
            "Playwright is required for UI runs. Install: pip install -e 'harness[ui]' && playwright install chromium"
        ) from exc

    driver_cls = DRIVER_CLASSES[fw]

    def ask_native(question: str, timeout_s: float) -> UIAskResult:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context()
            if trace_path:
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            driver = driver_cls(page, url)
            try:
                driver.ensure_ready()
                result = driver.ask(question, timeout_s=timeout_s)
            except Exception as exc:  # noqa: BLE001
                result = UIAskResult(pred_sql=None, latency_ms=0, error=str(exc))
                if trace_path:
                    trace_file = Path(trace_path) / f"trace_{fw}_{int(timeout_s)}.zip"
                    trace_file.parent.mkdir(parents=True, exist_ok=True)
                    context.tracing.stop(path=str(trace_file))
                browser.close()
                return result
            if trace_path and result.error:
                trace_file = Path(trace_path) / f"trace_{fw}_failure.zip"
                trace_file.parent.mkdir(parents=True, exist_ok=True)
                context.tracing.stop(path=str(trace_file))
            elif trace_path:
                context.tracing.stop()
            browser.close()
            return result

    return ask_native


class UIAskerSession:
    """Reuses one browser context for an entire benchmark run (faster than per-question launch)."""

    def __init__(
        self,
        *,
        framework: str,
        ui_url: Optional[str] = None,
        trace_dir: Optional[Path] = None,
        headless: bool = True,
    ) -> None:
        self.framework = normalize_framework(framework)
        self.ui_url = (ui_url or FRAMEWORK_URLS[self.framework].default_url).rstrip("/")
        self.trace_dir = trace_dir
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._driver = None

    def __enter__(self) -> "UIAskerSession":
        if os.environ.get("NL2SQL_PLAYWRIGHT_MCP_CMD"):
            return self
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context()
        if self.trace_dir:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
            self._context.tracing.start(screenshots=True, snapshots=True, sources=True)
        self._page = self._context.new_page()
        driver_cls = DRIVER_CLASSES[self.framework]
        self._driver = driver_cls(self._page, self.ui_url)
        self._driver.ensure_ready()
        return self

    def __exit__(self, *args) -> None:
        if self._context and self.trace_dir:
            trace_file = self.trace_dir / f"trace_{self.framework}_session.zip"
            self._context.tracing.stop(path=str(trace_file))
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def ask(self, question: str, *, timeout_s: float) -> UIAskResult:
        if os.environ.get("NL2SQL_PLAYWRIGHT_MCP_CMD"):
            return _mcp_ask(
                self.framework,
                self.ui_url,
                question,
                timeout_s=timeout_s,
                trace_dir=str(self.trace_dir) if self.trace_dir else None,
            )
        if self._driver is None:
            raise UIRunnerError("UI session not started")
        try:
            return self._driver.ask(question, timeout_s=timeout_s)
        except Exception as exc:  # noqa: BLE001
            if self._context and self.trace_dir:
                trace_file = self.trace_dir / f"trace_{self.framework}_failure.zip"
                self._context.tracing.stop(path=str(trace_file))
                self._context.tracing.start(screenshots=True, snapshots=True, sources=True)
            return UIAskResult(pred_sql=None, latency_ms=0, error=str(exc))

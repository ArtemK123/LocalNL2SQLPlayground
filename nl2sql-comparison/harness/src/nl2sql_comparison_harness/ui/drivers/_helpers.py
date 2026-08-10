from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from nl2sql_comparison_harness.ui.sql_extract import extract_sql_from_page_text

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


def wait_for_sql_in_text(
    get_text_fn,
    *,
    timeout_s: float,
    poll_interval_s: float = 0.5,
    baseline: str = "",
) -> tuple[Optional[str], str]:
    deadline = time.monotonic() + timeout_s
    last_text = baseline
    while time.monotonic() < deadline:
        last_text = get_text_fn() or ""
        if baseline and last_text == baseline:
            time.sleep(poll_interval_s)
            continue
        scan_text = last_text
        if baseline and last_text.startswith(baseline):
            scan_text = last_text[len(baseline) :]
        sql = extract_sql_from_page_text(scan_text)
        if sql:
            return sql, last_text
        time.sleep(poll_interval_s)
    scan_text = last_text
    if baseline and last_text.startswith(baseline):
        scan_text = last_text[len(baseline) :]
    sql = extract_sql_from_page_text(scan_text)
    if sql:
        return sql, last_text
    return None, last_text


def first_visible_locator(page: "Page", selectors: list[str], *, timeout_ms: int = 5000) -> Optional["Locator"]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    for sel in selectors:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=timeout_ms)
            return loc
        except PlaywrightTimeout:
            continue
    return None


def fill_chat_and_submit(page: "Page", question: str, *, timeout_ms: int = 10_000) -> None:
    input_loc = first_visible_locator(
        page,
        [
            "textarea:visible",
            '[placeholder="Type your message here..."]',
            '[placeholder="Type your message here"]',
            '[placeholder*="Type your message" i]',
            "#chat-input textarea",
            "#chat-input",
            "#message-composer textarea",
            "#message-composer",
            '[placeholder*="message" i]',
            '[data-testid="chat-input"]',
            "textarea",
            '[contenteditable="true"]',
            '[role="textbox"]',
            'input[type="text"]',
            ".chat-input textarea",
        ],
        timeout_ms=timeout_ms,
    )
    if input_loc is None:
        raise RuntimeError("Could not find chat input on page")
    input_loc.click()
    input_loc.fill(question)
    page.keyboard.press("Enter")

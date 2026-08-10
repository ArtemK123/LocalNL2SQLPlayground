#!/usr/bin/env python3
"""One-shot Chat2DB Custom AI (Ollama) setup via Playwright — run when chat2db_data volume is fresh."""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Chat2DB Custom AI provider (Ollama) in the UI.")
    parser.add_argument("--ui-url", default=os.environ.get("CHAT2DB_UI_URL", "http://127.0.0.1:10825"))
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
    parser.add_argument("--model", default=os.environ.get("OLLAMA_PRIMARY_MODEL", "qwen2.5:7b-instruct"))
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Install harness[ui] and run: playwright install chromium", file=sys.stderr)
        return 2

    print(
        f"Open {args.ui_url} and configure Custom AI → Ollama base {args.ollama_url}, model {args.model}. "
        "Chat2DB has no stable REST API for this step; complete the settings UI manually or extend selectors here.",
        flush=True,
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_page()
        page.goto(args.ui_url, wait_until="domcontentloaded", timeout=60_000)
        if args.headed:
            print("Configure Custom AI in the browser, then press Enter to close.", flush=True)
            input()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Optional MCP bridge for UI debugging when native Playwright selectors break."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from typing import Any


def _framework_instructions(framework: str) -> str:
    instructions = {
        "chat2db": "Open SQL chat, submit question, extract SQL from assistant response.",
        "wrenai": "Open ask view, submit question, wait for finished task, extract SQL.",
        "langchain": "Chainlit login if needed, send question, extract ```sql block.",
        "dbgpt": "DbGPT chat: send question, extract SQL snippet.",
        "premsql": "PremSQL playground: send question, extract SQL.",
        "vanna": "Vanna chat UI: send question, extract SQL code block.",
    }
    return instructions.get(framework, "Submit question in UI and extract generated SQL.")


def main() -> int:
    t0 = time.perf_counter()
    payload = json.loads(sys.stdin.read() or "{}")
    framework = str(payload.get("framework") or "").strip().lower()
    question = str(payload.get("question") or "").strip()
    ui_url = str(payload.get("ui_url") or "").strip()
    timeout_s = float(payload.get("timeout_s") or 300.0)

    prompt = {
        "task": "NL2SQL UI ask via Playwright MCP",
        "framework": framework,
        "ui_url": ui_url,
        "question": question,
        "timeout_s": timeout_s,
        "instructions": _framework_instructions(framework),
        "expected_output_schema": {"pred_sql": "string|null", "error": "string|null", "raw": "object"},
    }

    executor = os.environ.get("NL2SQL_PLAYWRIGHT_MCP_EXEC_CMD", "").strip()
    if not executor:
        out = {
            "pred_sql": None,
            "error": "NL2SQL_PLAYWRIGHT_MCP_EXEC_CMD is not configured.",
            "raw": {"prompt": prompt},
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
        return 0

    proc = subprocess.run(
        shlex.split(executor),
        input=json.dumps(prompt, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=max(timeout_s + 10.0, 30.0),
        check=False,
    )
    if proc.returncode != 0:
        out = {
            "pred_sql": None,
            "error": f"MCP executor failed (exit {proc.returncode}): {(proc.stderr or '').strip()}",
            "raw": {},
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
        return 0

    text = (proc.stdout or "").strip()
    if not text:
        out = {
            "pred_sql": None,
            "error": "MCP executor returned empty stdout.",
            "raw": {},
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
        return 0

    parsed: dict[str, Any] = json.loads(text)
    parsed.setdefault("pred_sql", None)
    parsed.setdefault("error", None)
    parsed.setdefault("raw", {})
    parsed.setdefault("latency_ms", int((time.perf_counter() - t0) * 1000))
    sys.stdout.write(json.dumps(parsed, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

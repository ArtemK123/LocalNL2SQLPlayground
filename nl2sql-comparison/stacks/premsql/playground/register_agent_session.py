"""Register AgentServer URL with the playground Django API (idempotent)."""
from __future__ import annotations

import os
import sys
import time

import requests

BACKEND = os.environ.get(
    "PREMSQL_BACKEND_API_URL", "http://premsql-playground-api:8000/api"
).rstrip("/")
if not BACKEND.endswith("/api"):
    BACKEND = f"{BACKEND}/api"
AGENT_URL = os.environ.get("PREMSQL_AGENT_URL", "http://premsql-api:8010").rstrip("/")


def wait_backend(timeout_s: int = 180) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = requests.get(
                f"{BACKEND}/session/list/",
                params={"page": 1, "page_size": 5},
                timeout=5,
            )
            if r.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(3)
    raise SystemExit(f"Playground API not ready: {BACKEND}")


def wait_agent(timeout_s: int = 300) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{AGENT_URL}/health", timeout=5)
            if r.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(5)
    raise SystemExit(f"AgentServer not ready: {AGENT_URL}")


def main() -> None:
    wait_backend()
    wait_agent()

    listed = requests.get(
        f"{BACKEND}/session/list/",
        params={"page": 1, "page_size": 100},
        timeout=30,
    )
    listed.raise_for_status()
    sessions = listed.json().get("sessions") or []
    for s in sessions:
        base = s.get("base_url") if isinstance(s, dict) else getattr(s, "base_url", None)
        if base and base.rstrip("/") == AGENT_URL:
            name = s.get("session_name") if isinstance(s, dict) else getattr(s, "session_name", "")
            print(f"SESSION_EXISTS name={name} agent={AGENT_URL}")
            return

    created = requests.post(
        f"{BACKEND}/session/create",
        json={"base_url": AGENT_URL},
        timeout=60,
    )
    if created.status_code == 200:
        body = created.json()
        name = body.get("session_name", "")
        print(f"SESSION_CREATED name={name} agent={AGENT_URL}")
        return
    print(f"SESSION_CREATE_FAILED status={created.status_code} body={created.text[:500]}")
    sys.exit(1)


if __name__ == "__main__":
    main()

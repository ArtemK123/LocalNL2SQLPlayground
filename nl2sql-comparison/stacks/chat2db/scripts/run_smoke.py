"""Run smoke tests for the Chat2DB OLAP stack (host ports from .env / defaults)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

STEPS = [
    ("OLAP + ETL data checks", [sys.executable, str(SCRIPTS / "smoke_olap_etl.py")]),
    ("Ollama model tag", [sys.executable, str(SCRIPTS / "smoke_ollama_model.py")]),
    ("Ollama SQL generation", [sys.executable, str(SCRIPTS / "smoke_ollama_sql.py")]),
    ("Chat2DB HTTP", [sys.executable, str(SCRIPTS / "smoke_chat2db_http.py")]),
]


def main() -> int:
    for label, cmd in STEPS:
        print(f"\n=== {label} ===", flush=True)
        rc = subprocess.call(cmd)
        if rc != 0:
            print(f"FAILED: {label} (exit {rc})", flush=True)
            return rc
    print("\nAll smoke steps passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

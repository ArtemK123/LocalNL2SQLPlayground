#!/bin/bash
set -euo pipefail
echo "=== chainlit logs (last 40) ==="
docker logs --tail 40 nl2sql-comparison-langchain-chainlit-1 2>&1 || true
echo ""
echo "=== curl 8501 ==="
curl -sS -o /dev/null -w "GET / -> %{http_code}\n" --max-time 20 http://127.0.0.1:8501/ || echo "curl failed: $?"
curl -sS -o /dev/null -w "GET /chainlit -> %{http_code}\n" --max-time 20 http://127.0.0.1:8501/chainlit || true
ss -tlnp | grep 8501 || netstat -tlnp 2>/dev/null | grep 8501 || true

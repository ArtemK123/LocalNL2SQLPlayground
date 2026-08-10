#!/bin/bash
# Read-only: running NL2SQL containers + stack health endpoints.
set -euo pipefail
echo "=== docker ps (nl2sql host) ==="
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true

echo ""
echo "=== health endpoints ==="
for url in \
  "http://127.0.0.1:8011/healthz" \
  "http://127.0.0.1:8501/" \
  "http://127.0.0.1:3001/" \
  "http://127.0.0.1:8012/healthz"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$url" 2>/dev/null || echo "000")
  echo "$url -> HTTP $code"
done

echo ""
echo "=== compose/.env Ollama vars (if present) ==="
ENV="/home/ec2-user/nl2sql-comparison/compose/.env"
grep -E '^OLLAMA_|^BIRD_|^WREN_' "$ENV" 2>/dev/null | head -20 || echo "(no env)"

echo ""
echo "NL2SQL_CHECK_DONE"

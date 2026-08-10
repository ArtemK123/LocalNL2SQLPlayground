#!/bin/bash
# Read-only LangChain health on NL2SQL host (no redeploy).
set -euo pipefail

COMPOSE_DIR="/home/ec2-user/nl2sql-comparison/compose"
STACK_COMPOSE="stacks/langchain/docker-compose.yml"

echo "=== Host ==="
hostname
date -u +"%Y-%m-%dT%H:%M:%SZ"
systemctl is-active docker 2>/dev/null || echo "docker: unknown"

echo ""
echo "=== Package dir ==="
if [ -d "$COMPOSE_DIR" ]; then
  ls -la "$COMPOSE_DIR" | head -5
  if [ -f "$COMPOSE_DIR/.env" ]; then
    echo ".env keys:" $(grep -E '^(BIRD_PG_HOST|OLLAMA_HOST|OLLAMA_PRIMARY)=' "$COMPOSE_DIR/.env" 2>/dev/null | sed 's/=.*/=.../' || true)
  fi
else
  echo "MISSING: $COMPOSE_DIR (stack never deployed or wiped)"
fi

echo ""
echo "=== Docker containers (langchain-related) ==="
docker ps -a --filter "name=langchain" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || docker ps -a | grep -i langchain || echo "(no langchain containers)"

echo ""
echo "=== docker compose ps (langchain stack) ==="
if [ -f "$COMPOSE_DIR/$STACK_COMPOSE" ]; then
  cd "$COMPOSE_DIR"
  docker compose --env-file .env -f "$STACK_COMPOSE" ps -a 2>/dev/null || docker compose -f "$STACK_COMPOSE" ps -a 2>/dev/null || echo "compose ps failed"
else
  echo "SKIP: $COMPOSE_DIR/$STACK_COMPOSE not found"
fi

echo ""
echo "=== HTTP probes ==="
probe() {
  local name="$1" url="$2"
  if curl -sf --max-time 10 "$url" >/dev/null 2>&1; then
    echo "OK   $name $url"
    curl -sf --max-time 10 "$url" 2>/dev/null | head -c 200 || true
    echo ""
  else
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$url" 2>/dev/null || echo "000")
    echo "FAIL $name $url (http=$code)"
  fi
}

probe "langchain-api" "http://127.0.0.1:8011/healthz"
probe "chainlit-ui" "http://127.0.0.1:8501"

echo ""
echo "=== Compose health (if services exist) ==="
if [ -f "$COMPOSE_DIR/$STACK_COMPOSE" ]; then
  cd "$COMPOSE_DIR"
  docker compose --env-file .env -f "$STACK_COMPOSE" ps --format json 2>/dev/null | head -c 2000 || true
fi

echo ""
echo "=== Recent logs (langchain-api, last 15 lines) ==="
docker logs --tail 15 nl2sql-comparison-langchain-langchain-api-1 2>/dev/null \
  || docker logs --tail 15 "$(docker ps -aq --filter name=langchain-api | head -1)" 2>/dev/null \
  || echo "(no langchain-api container logs)"

echo "CHECK_DONE"

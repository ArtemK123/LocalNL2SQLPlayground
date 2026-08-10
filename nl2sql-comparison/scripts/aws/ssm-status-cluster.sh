#!/bin/bash
# Read-only cluster application status (NL2SQL host + optional GPU/DB probes).
# Exit: 0=all critical OK, 1=degraded, 2=down
set -uo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/home/ec2-user/nl2sql-comparison/compose}"
CURL_TIMEOUT="${STATUS_CURL_TIMEOUT:-10}"
ROLE="${STATUS_ROLE:-nl2sql}"

status_line() {
  echo "STATUS $*"
}

echo "=== Cluster status (role=${ROLE}) ==="
echo "host=$(hostname) utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
overall=0
issues=()

if [[ "$ROLE" == "nl2sql" ]]; then
  echo ""
  echo "=== Running containers ==="
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true

  echo ""
  echo "=== Stack health endpoints ==="
  declare -A endpoints=(
    ["langchain-api"]="http://127.0.0.1:8011/healthz"
    ["chainlit-ui"]="http://127.0.0.1:8501/"
    ["dbgpt-api"]="http://127.0.0.1:8012/healthz"
    ["wrenai-ui"]="http://127.0.0.1:3001/"
    ["vanna-api"]="http://127.0.0.1:8001/"
    ["chat2db-ui"]="http://127.0.0.1:10825/"
  )
  active=()
  for name in "${!endpoints[@]}"; do
    url="${endpoints[$name]}"
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$CURL_TIMEOUT" "$url" 2>/dev/null || echo "000")
    if [[ "$code" =~ ^2 ]]; then
      echo "OK   ${name} ${url} -> HTTP ${code}"
      active+=("$name")
      status_line "endpoint=${name} state=up http=${code}"
    else
      echo "---- ${name} ${url} -> HTTP ${code}"
      status_line "endpoint=${name} state=down http=${code}"
    fi
  done
  if [[ ${#active[@]} -eq 0 ]]; then
    issues+=("no_stack_endpoints_up")
    overall=2
  else
    status_line "active_stacks=$(IFS=,; echo "${active[*]}")"
  fi

  echo ""
  echo "=== compose/.env (selected) ==="
  ENV="${COMPOSE_DIR}/.env"
  if [[ -f "$ENV" ]]; then
    grep -E '^(BIRD_PG_HOST|OLLAMA_HOST|OLLAMA_PRIMARY_MODEL|OLLAMA_ACTIVE_MODEL|WREN_TARGET)=' "$ENV" 2>/dev/null \
      | sed 's/=.*/=.../' || true
  else
    echo "(missing ${ENV})"
    overall=2
  fi
fi

if [[ "$ROLE" == "gpu" ]]; then
  echo ""
  echo "=== GPU / Ollama ==="
  if command -v nvidia-smi &>/dev/null; then
    nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null || true
  fi
  active_model="unknown"
  ENV="${COMPOSE_DIR}/.env"
  if [[ -f "$ENV" ]]; then
    active_model=$(grep -E '^OLLAMA_ACTIVE_MODEL=' "$ENV" | head -1 | cut -d= -f2- | tr -d '"' \
      || grep -E '^OLLAMA_PRIMARY_MODEL=' "$ENV" | head -1 | cut -d= -f2- | tr -d '"')
  fi
  status_line "gpu_active_model=${active_model}"
  echo "OLLAMA_ACTIVE_MODEL=${active_model}"
  if curl -sf --max-time "$CURL_TIMEOUT" http://127.0.0.1:11434/api/tags >/tmp/gpu_tags.json 2>/dev/null; then
    jq -r '.models[]?.name' /tmp/gpu_tags.json 2>/dev/null | sed 's/^/  model: /' || true
    status_line "component=ollama state=healthy"
  else
    status_line "component=ollama state=down"
    issues+=("ollama_down")
    overall=2
  fi
fi

if [[ "$ROLE" == "db" ]]; then
  echo ""
  echo "=== PostgreSQL ==="
  pg_cid=$(docker ps -q -f name=postgres 2>/dev/null | head -1)
  if [[ -n "$pg_cid" ]]; then
    docker ps -f id="$pg_cid" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    table_count=$(docker exec "$pg_cid" psql -U olap -d bird -tAc \
      "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';" 2>/dev/null \
      || echo "?")
    status_line "component=postgres state=healthy public_tables=${table_count}"
    echo "public_tables=${table_count}"
  else
    status_line "component=postgres state=down"
    issues+=("postgres_container_down")
    overall=2
  fi
fi

echo ""
if [[ "$overall" -ge 2 ]]; then
  status_line "overall=down issues=$(IFS=,; echo "${issues[*]}")"
  echo "CLUSTER_STATUS=down"
  exit 2
fi
if [[ ${#issues[@]} -gt 0 ]]; then
  status_line "overall=degraded issues=$(IFS=,; echo "${issues[*]}")"
  echo "CLUSTER_STATUS=degraded"
  exit 1
fi
status_line "overall=healthy"
echo "CLUSTER_STATUS=healthy"
exit 0

#!/bin/bash
# Read-only LangChain stack status on the NL2SQL host.
# Emits machine-readable STATUS lines plus human sections.
# Exit: 0=healthy, 1=degraded, 2=down
set -uo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/home/ec2-user/nl2sql-comparison/compose}"
STACK_COMPOSE="stacks/langchain/docker-compose.yml"
CURL_TIMEOUT="${STATUS_CURL_TIMEOUT:-15}"
LOG_TAIL="${STATUS_LOG_TAIL:-20}"

overall=0
issues=()

status_line() {
  echo "STATUS $*"
}

http_probe() {
  local name="$1" url="$2"
  local code body t0 t1 ms
  t0=$(date +%s%3N 2>/dev/null || echo 0)
  code=$(curl -s -o /tmp/status_body.txt -w "%{http_code}" --max-time "$CURL_TIMEOUT" "$url" 2>/dev/null || echo "000")
  t1=$(date +%s%3N 2>/dev/null || echo 0)
  if [[ "$t0" =~ ^[0-9]+$ ]] && [[ "$t1" =~ ^[0-9]+$ ]]; then
    ms=$((t1 - t0))
  else
    ms="-"
  fi
  body=$(head -c 120 /tmp/status_body.txt 2>/dev/null | tr '\n' ' ')
  if [[ "$code" =~ ^2 ]]; then
    status_line "component=${name} state=healthy http=${code} latency_ms=${ms}"
    echo "OK   ${name} ${url} (http=${code}, ${ms}ms)"
    [[ -n "$body" ]] && echo "     body: ${body}"
    return 0
  fi
  status_line "component=${name} state=unhealthy http=${code} latency_ms=${ms}"
  echo "FAIL ${name} ${url} (http=${code}, ${ms}ms)"
  issues+=("${name}:http_${code}")
  overall=$((overall > 1 ? overall : 1))
  return 1
}

echo "=== LangChain stack status ==="
echo "host=$(hostname) utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo ""
echo "=== Containers ==="
docker ps -a --filter "name=langchain" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true
api_running=$(docker ps --filter "name=langchain-api" --format '{{.Names}}' 2>/dev/null | grep -c . || true)
chainlit_running=$(docker ps --filter "name=chainlit" --format '{{.Names}}' 2>/dev/null | grep -c . || true)

if [[ "${api_running:-0}" -eq 0 ]]; then
  status_line "component=langchain-api state=down detail=container_not_running"
  issues+=("langchain-api:down")
  overall=2
else
  status_line "component=langchain-api state=running containers=${api_running}"
fi
if [[ "${chainlit_running:-0}" -eq 0 ]]; then
  status_line "component=chainlit state=down detail=container_not_running"
  issues+=("chainlit:down")
  overall=2
else
  status_line "component=chainlit state=running containers=${chainlit_running}"
fi

echo ""
echo "=== HTTP probes (timeout=${CURL_TIMEOUT}s) ==="
http_probe "langchain-api" "http://127.0.0.1:8011/healthz" || true
http_probe "chainlit-ui" "http://127.0.0.1:8501/" || true

echo ""
echo "=== API metrics ==="
metrics=$(curl -sf --max-time "$CURL_TIMEOUT" "http://127.0.0.1:8011/metrics" 2>/dev/null || true)
if [[ -n "$metrics" ]]; then
  echo "$metrics"
  req_total=$(echo "$metrics" | awk '/nl2sql_requests_total/ {print $2}')
  err_total=$(echo "$metrics" | awk '/nl2sql_errors_total/ {print $2}')
  status_line "component=langchain-api-metrics requests_total=${req_total:-0} errors_total=${err_total:-0}"
else
  echo "(metrics unavailable)"
  status_line "component=langchain-api-metrics state=unknown"
fi

echo ""
echo "=== Dependencies (from NL2SQL host) ==="
ENV_FILE="${COMPOSE_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
  ollama_host=$(grep -E '^OLLAMA_HOST=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' || true)
  bird_host=$(grep -E '^BIRD_PG_HOST=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' || true)
  primary_model=$(grep -E '^OLLAMA_PRIMARY_MODEL=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' || true)
  echo "OLLAMA_HOST=${ollama_host:-unset} model=${primary_model:-unset}"
  echo "BIRD_PG_HOST=${bird_host:-unset}"

  if [[ -n "${ollama_host:-}" ]]; then
    if [[ "$ollama_host" =~ ^https?:// ]]; then
      ollama_base="${ollama_host%/}"
    else
      ollama_base="http://${ollama_host}:11434"
    fi
    ollama_url="${ollama_base}/api/tags"
    if curl -sf --max-time "$CURL_TIMEOUT" "$ollama_url" >/tmp/ollama_tags.json 2>/dev/null; then
      model_count=$(jq -r '.models | length' /tmp/ollama_tags.json 2>/dev/null || echo "?")
      status_line "component=ollama state=healthy url=${ollama_base} models=${model_count}"
      echo "OK   ollama ${ollama_url} (models=${model_count})"
    else
      status_line "component=ollama state=unhealthy url=${ollama_base}"
      echo "FAIL ollama ${ollama_url}"
      issues+=("ollama:unreachable")
      overall=$((overall > 1 ? overall : 1))
    fi
  fi

  if [[ -n "${bird_host:-}" ]]; then
    if timeout 5 bash -c "echo >/dev/tcp/${bird_host}/5432" 2>/dev/null; then
      status_line "component=postgres state=healthy host=${bird_host} port=5432"
      echo "OK   postgres tcp://${bird_host}:5432"
    else
      status_line "component=postgres state=unhealthy host=${bird_host} port=5432"
      echo "FAIL postgres tcp://${bird_host}:5432"
      issues+=("postgres:unreachable")
      overall=2
    fi
  fi
else
  echo "WARN missing ${ENV_FILE}"
  status_line "component=env state=missing path=${ENV_FILE}"
  overall=2
fi

echo ""
echo "=== Container stats (snapshot) ==="
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" \
  $(docker ps -q --filter "name=langchain" 2>/dev/null) 2>/dev/null || echo "(no stats)"

echo ""
echo "=== Recent langchain-api logs (last ${LOG_TAIL}) ==="
docker logs --tail "$LOG_TAIL" nl2sql-comparison-langchain-langchain-api-1 2>&1 \
  || docker logs --tail "$LOG_TAIL" "$(docker ps -aq --filter name=langchain-api | head -1)" 2>&1 \
  || echo "(no api logs)"

last_api_log=$(docker logs --tail 3 nl2sql-comparison-langchain-langchain-api-1 2>&1 | tail -1 || true)
if echo "$last_api_log" | grep -q 'POST /v1/chat' && ! echo "$last_api_log" | grep -q '200 OK'; then
  status_line "component=langchain-api state=busy detail=possible_in_flight_chat"
  echo "NOTE API may be processing a /v1/chat request (Arctic ~90-120s per query is normal)."
  overall=$((overall > 1 ? overall : 1))
fi

echo ""
echo "=== Recent chainlit logs (last ${LOG_TAIL}) ==="
docker logs --tail "$LOG_TAIL" nl2sql-comparison-langchain-chainlit-1 2>&1 \
  || echo "(no chainlit logs)"

if docker logs --tail 100 nl2sql-comparison-langchain-chainlit-1 2>&1 | grep -Eiq 'autocollapse|no such table: (threads|steps)|OperationalError.*steps'; then
  status_line "component=chainlit state=degraded detail=sqlite_schema_mismatch"
  echo "WARN chainlit SQLite schema missing or outdated. UI may hang on chat."
  echo "     Fix: rebuild chainlit (latest app.py) and recreate the UI container/volume."
  issues+=("chainlit:sqlite_schema")
  overall=$((overall > 1 ? overall : 1))
fi

echo ""
if [[ ${#issues[@]} -eq 0 ]]; then
  status_line "overall=healthy"
  echo "LANGCHAIN_STATUS=healthy"
  exit 0
fi

if [[ "$overall" -ge 2 ]]; then
  status_line "overall=down issues=$(IFS=,; echo "${issues[*]}")"
  echo "LANGCHAIN_STATUS=down"
  exit 2
fi

status_line "overall=degraded issues=$(IFS=,; echo "${issues[*]}")"
echo "LANGCHAIN_STATUS=degraded"
exit 1

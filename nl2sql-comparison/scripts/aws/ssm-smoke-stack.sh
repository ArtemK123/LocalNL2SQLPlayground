#!/bin/bash
# Deploy one NL2SQL stack on the NL2SQL EC2 host and run its health smoke via SSM.
# Requires remote GPU Ollama (OLLAMA_HOST) and DB (BIRD_PG_HOST). No colocated Ollama in v1.
set -uxo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
BUCKET="${BIRD_DATASET_BUCKET:?set BIRD_DATASET_BUCKET (e.g. nl2sql-comparison-bird-<account-id>)}"
VERSION="${BIRD_DATASET_VERSION:-2026-05-24}"
DB_IP="${BIRD_PG_HOST:?set BIRD_PG_HOST}"
STACK="${NL2SQL_STACK:?set NL2SQL_STACK}"
OLLAMA_BASE="${OLLAMA_HOST:?set OLLAMA_HOST}"
USE_LOCAL_OLLAMA="${USE_LOCAL_OLLAMA:-false}"

install_compose() {
  mkdir -p /usr/local/lib/docker/cli-plugins
  if ! docker compose version >/dev/null 2>&1; then
    curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-$(uname -m)" \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  fi
}

ensure_docker_network() {
  docker network inspect nl2sql-comparison-net >/dev/null 2>&1 \
    || docker network create nl2sql-comparison-net
}

dnf install -y docker awscli jq || true
systemctl enable docker
systemctl start docker
install_compose
ensure_docker_network

rm -rf /home/ec2-user/nl2sql-comparison
mkdir -p /home/ec2-user/nl2sql-comparison
aws s3 cp "s3://${BUCKET}/nl2sql-comparison/bird/${VERSION}/package.tgz" /tmp/nl2sql.tgz
tar -xzf /tmp/nl2sql.tgz -C /home/ec2-user/nl2sql-comparison
chown -R ec2-user:ec2-user /home/ec2-user/nl2sql-comparison
cd /home/ec2-user/nl2sql-comparison/compose
cp -f ../env.aws.example .env
SQL_MODEL="${OLLAMA_SQL_MODEL:-arctic-text2sql-r1-7b:q4_k_m}"
GENERAL_MODEL="${OLLAMA_GENERAL_MODEL:-qwen2.5-coder:14b-instruct-q8_0}"
case "${STACK}" in
  chat2db|dbgpt)
    PRIMARY_MODEL="${OLLAMA_PRIMARY_MODEL:-$GENERAL_MODEL}"
    ;;
  *)
    PRIMARY_MODEL="${OLLAMA_PRIMARY_MODEL:-$SQL_MODEL}"
    ;;
esac
FALLBACK_MODEL="${OLLAMA_FALLBACK_MODEL:-$PRIMARY_MODEL}"
# Wren: retrieval/indexing defaults (applied on every wrenai deploy).
if [ "${STACK}" = "wrenai" ]; then
  WREN_COLUMN_INDEXING_BATCH_SIZE="${WREN_COLUMN_INDEXING_BATCH_SIZE:-8}"
  WREN_TABLE_RETRIEVAL_SIZE="${WREN_TABLE_RETRIEVAL_SIZE:-75}"
  WREN_TABLE_COLUMN_RETRIEVAL_SIZE="${WREN_TABLE_COLUMN_RETRIEVAL_SIZE:-500}"
fi
# Wren: default to all discovered tables; infer PostgreSQL schema layout from DB.
if [ "${STACK}" = "wrenai" ] && [ -z "${WREN_TARGET_TABLES:-}" ]; then
  WREN_TARGET_TABLES="*"
fi
if [ "${STACK}" = "wrenai" ] && [ -z "${WREN_TARGET_SCHEMAS:-}" ]; then
  PG_USER="${NL2SQL_RO_USER:-nl2sql_ro}"
  PG_PASS="${NL2SQL_RO_PASSWORD:-nl2sql_ro}"
  PG_DB="${BIRD_PG_DB:-bird}"
  public_n=$(docker run --rm -e PGPASSWORD="${PG_PASS}" postgres:16-alpine \
    psql -h "${DB_IP}" -U "${PG_USER}" -d "${PG_DB}" -tAc \
    "SELECT COUNT(*)::int FROM information_schema.tables WHERE table_schema='public' AND table_type IN ('BASE TABLE','VIEW')" \
    2>/dev/null | tr -d '[:space:]') || public_n=0
  minidev_n=$(docker run --rm -e PGPASSWORD="${PG_PASS}" postgres:16-alpine \
    psql -h "${DB_IP}" -U "${PG_USER}" -d "${PG_DB}" -tAc \
    "SELECT COUNT(*)::int FROM information_schema.tables WHERE table_schema='formula_1' AND table_type IN ('BASE TABLE','VIEW')" \
    2>/dev/null | tr -d '[:space:]') || minidev_n=0
  if [ "${public_n:-0}" -gt 15 ] && [ "${minidev_n:-0}" -lt 5 ]; then
    WREN_TARGET_SCHEMAS="public"
    echo "WREN_SCHEMA_DETECT public_tables=${public_n} formula_1_tables=${minidev_n}"
  else
    WREN_TARGET_SCHEMAS="california_schools,card_games,codebase_community,debit_card_specializing,european_football_2,financial,formula_1,student_club,superhero,thrombosis_prediction,toxicology"
    echo "WREN_SCHEMA_DETECT minidev_schemas public_tables=${public_n} formula_1_tables=${minidev_n}"
  fi
fi
patch_env() {
  local key="$1" val="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${val}|" .env
  else
    echo "${key}=${val}" >> .env
  fi
}
LLM_BACKEND="${LLM_BACKEND:-ollama}"
VLLM_BASE="${VLLM_BASE_URL:-$OLLAMA_BASE}"
patch_env BIRD_PG_HOST "${DB_IP}"
patch_env OLLAMA_HOST "${OLLAMA_BASE}"
patch_env BIRD_PG_PORT "5432"
patch_env USE_LOCAL_OLLAMA "${USE_LOCAL_OLLAMA}"
patch_env LLM_BACKEND "${LLM_BACKEND}"
patch_env VLLM_BASE_URL "${VLLM_BASE}"
patch_env OLLAMA_PRIMARY_MODEL "\"${PRIMARY_MODEL}\""
patch_env OLLAMA_FALLBACK_MODEL "\"${FALLBACK_MODEL}\""
patch_env GENERATION_MODEL "ollama_chat/${PRIMARY_MODEL}"
if [ "${STACK}" = "langchain" ]; then
  # One-pass Arctic+vLLM uses SQL-fence prefill+stop; 512 tokens is enough for SQL body.
  # (Full CoT without prefill historically needed >=1024.)
  patch_env OLLAMA_NUM_PREDICT "${OLLAMA_NUM_PREDICT:-512}"
  patch_env SQL_REPAIR_MAX_RETRIES "${SQL_REPAIR_MAX_RETRIES:-0}"
  patch_env BIRD_DB_PROFILE "${BIRD_DB_PROFILE:-public}"
  patch_env SCHEMA_FINAL_TOP_K "${SCHEMA_FINAL_TOP_K:-8}"
  patch_env SCHEMA_SELECTOR_MODE "${SCHEMA_SELECTOR_MODE:-bm25}"
  patch_env SCHEMA_SOURCE "${SCHEMA_SOURCE:-bird_tables}"
  patch_env SCHEMA_BM25_INCLUDE_FK "${SCHEMA_BM25_INCLUDE_FK:-true}"
  patch_env ARCTIC_SQL_DIALECT "${ARCTIC_SQL_DIALECT:-sqlite}"
  patch_env SQL_EXEC_MODE "${SQL_EXEC_MODE:-skip}"
  patch_env NL2SQL_FAST_MODE "${NL2SQL_FAST_MODE:-true}"
  patch_env ARCTIC_SQL_FENCE_PREFILL "${ARCTIC_SQL_FENCE_PREFILL:-true}"
  patch_env LLM_HTTP_TIMEOUT_SEC "${LLM_HTTP_TIMEOUT_SEC:-20}"
fi
if [ -n "${WREN_TARGET_TABLES:-}" ]; then
  patch_env WREN_TARGET_TABLES "${WREN_TARGET_TABLES}"
fi
if [ -n "${WREN_TARGET_SCHEMAS:-}" ]; then
  patch_env WREN_TARGET_SCHEMAS "${WREN_TARGET_SCHEMAS}"
fi
if [ "${STACK}" = "wrenai" ]; then
  patch_env OLLAMA_EMBEDDING_MODEL "${OLLAMA_EMBEDDING_MODEL:-nomic-embed-text}"
  patch_env WREN_COLUMN_INDEXING_BATCH_SIZE "${WREN_COLUMN_INDEXING_BATCH_SIZE}"
  patch_env WREN_TABLE_RETRIEVAL_SIZE "${WREN_TABLE_RETRIEVAL_SIZE}"
  patch_env WREN_TABLE_COLUMN_RETRIEVAL_SIZE "${WREN_TABLE_COLUMN_RETRIEVAL_SIZE}"
fi

if [ "${LLM_BACKEND}" = "vllm" ]; then
  LLM_CHECK_URL="${VLLM_BASE%/}/v1/models"
  LLM_READY_GREP="${PRIMARY_MODEL%%/*}"
  [ -z "${LLM_READY_GREP}" ] && LLM_READY_GREP="Arctic"
else
  if [ "${USE_LOCAL_OLLAMA}" = "true" ]; then
    cat > docker-compose.gpu.cpu.yml <<'EOF'
services:
  ollama:
    deploy: {}
EOF
    docker compose -f docker-compose.gpu.yml -f docker-compose.gpu.cpu.yml up -d
    LLM_CHECK_URL="http://127.0.0.1:11434/api/tags"
  else
    LLM_CHECK_URL="${OLLAMA_BASE%/}/api/tags"
  fi
  LLM_READY_GREP="${PRIMARY_MODEL}"
fi

for i in $(seq 1 180); do
  if curl -sf "${LLM_CHECK_URL}" | grep -Fiq "${LLM_READY_GREP}"; then
    echo "LLM_READY backend=${LLM_BACKEND} url=${LLM_CHECK_URL} model=${PRIMARY_MODEL}"
    break
  fi
  sleep 10
done
curl -sf "${LLM_CHECK_URL}" | head -c 500 || true

COMPOSE_ENV=(--env-file .env)
COMPOSE_FILE="stacks/${STACK}/docker-compose.yml"
WREN_RESYNC_MODEL="${WREN_RESYNC_MODEL:-false}"

wren_onboarding_status() {
  curl -sf -X POST http://127.0.0.1:3001/api/graphql \
    -H 'Content-Type: application/json' \
    -d '{"query":"query { onboardingStatus { status } }"}' 2>/dev/null \
    | jq -r '.data.onboardingStatus.status // empty' 2>/dev/null || true
}

wren_use_bootstrap_profile() {
  if [ "${WREN_RESYNC_MODEL}" = "true" ]; then
    return 0
  fi
  local st
  st="$(wren_onboarding_status)"
  [ "${st}" != "ONBOARDING_FINISHED" ]
}

if [ "${STACK}" = "wrenai" ] && [ "${WREN_RESYNC_MODEL}" != "true" ] && [ "$(wren_onboarding_status)" = "ONBOARDING_FINISHED" ]; then
  echo "WREN_DEPLOY_NO_RESYNC onboarding=ONBOARDING_FINISHED (rolling up; no bootstrap profile)"
  docker compose "${COMPOSE_ENV[@]}" -f "${COMPOSE_FILE}" up -d --build
elif [ "${STACK}" = "wrenai" ] && wren_use_bootstrap_profile; then
  echo "WREN_DEPLOY_BOOTSTRAP resync=${WREN_RESYNC_MODEL}"
  docker compose "${COMPOSE_ENV[@]}" -f "${COMPOSE_FILE}" down || true
  docker compose "${COMPOSE_ENV[@]}" -f "${COMPOSE_FILE}" --profile wren-bootstrap up -d --build
else
  docker compose "${COMPOSE_ENV[@]}" -f "${COMPOSE_FILE}" down || true
  if [ "${STACK}" = "langchain" ]; then
    # Langchain-api is COPY-only; bust cache after S3 package updates.
    docker compose "${COMPOSE_ENV[@]}" -f "${COMPOSE_FILE}" build --no-cache langchain-api
    docker compose "${COMPOSE_ENV[@]}" -f "${COMPOSE_FILE}" up -d
  else
    docker compose "${COMPOSE_ENV[@]}" -f "${COMPOSE_FILE}" up -d --build
  fi
fi

case "${STACK}" in
  langchain) URL="http://127.0.0.1:8011/healthz" ;;
  dbgpt) URL="http://127.0.0.1:8012/healthz" ;;
  premsql) URL="http://127.0.0.1:8501/_stcore/health" ;;
  vanna) URL="http://127.0.0.1:8001/docs" ;;
  wrenai) URL="http://127.0.0.1:3001" ;;
  chat2db) URL="http://127.0.0.1:10825" ;;
  *) echo "Unknown stack ${STACK}"; exit 1 ;;
esac

RETRIES=60
[ "${STACK}" = "wrenai" ] && RETRIES=90
for i in $(seq 1 "${RETRIES}"); do
  if curl -sf "${URL}" >/dev/null; then
    echo "SMOKE_OK stack=${STACK} url=${URL}"
    break
  fi
  sleep 10
done
if ! curl -sf "${URL}" >/dev/null; then
  echo "SMOKE_FAIL stack=${STACK} url=${URL}"
  exit 1
fi

if [ "${STACK}" = "premsql" ]; then
  for extra in "http://127.0.0.1:8010/health" "http://127.0.0.1:8000/api/session/list/?page=1&page_size=1"; do
    if ! curl -sf "${extra}" >/dev/null; then
      echo "SMOKE_FAIL stack=${STACK} url=${extra}"
      exit 1
    fi
  done
  echo "PREMSQL_PLAYGROUND_OK ui=8501 api=8000 agent=8010"
fi

# Simple smokes after HTTP health: DB reachable + minimal NL2SQL on API stacks (no harness/Playwright).
NL_QUESTION="${NL_SMOKE_QUESTION:-how many tables in db}"
PG_USER="${NL2SQL_RO_USER:-nl2sql_ro}"
PG_PASS="${NL2SQL_RO_PASSWORD:-nl2sql_ro}"
PG_DB="${BIRD_PG_DB:-bird}"

simple_db_smoke() {
  echo "DB_SMOKE_START host=${DB_IP} db=${PG_DB}"
  local count
  local schema_sql="SELECT COUNT(*)::int FROM information_schema.tables WHERE table_type IN ('BASE TABLE','VIEW')"
  if [ -n "${WREN_TARGET_SCHEMAS:-}" ]; then
    local in_list
    in_list=$(echo "${WREN_TARGET_SCHEMAS}" | tr ',' '\n' | sed "s/^/'/;s/$/'/" | paste -sd, -)
    schema_sql="SELECT COUNT(*)::int FROM information_schema.tables WHERE table_schema IN (${in_list}) AND table_type IN ('BASE TABLE','VIEW')"
  else
    schema_sql="${schema_sql} AND table_schema='public'"
  fi
  count=$(docker run --rm \
    -e PGPASSWORD="${PG_PASS}" \
    postgres:16-alpine \
    psql -h "${DB_IP}" -U "${PG_USER}" -d "${PG_DB}" -tAc \
    "${schema_sql}" \
    2>/dev/null) || {
    echo "DB_SMOKE_FAIL stack=${STACK}"
    return 1
  }
  count=$(echo "${count}" | tr -d '[:space:]')
  if [ -z "${count}" ] || [ "${count}" -lt 1 ] 2>/dev/null; then
    echo "DB_SMOKE_FAIL stack=${STACK} reason=bad_table_count count=${count}"
    return 1
  fi
  echo "DB_SMOKE_OK stack=${STACK} minidev_tables=${count}"
  return 0
}

simple_nl_smoke_api() {
  local port="$1"
  local url="http://127.0.0.1:${port}/v1/chat"
  local body
  body=$(printf '{"question":"%s"}' "${NL_QUESTION}")
  echo "NL_SMOKE_START stack=${STACK} url=${url} question=${NL_QUESTION}"
  local resp
  resp=$(curl -sf -m 1200 -X POST "${url}" -H "Content-Type: application/json" -d "${body}") || {
    echo "NL_SMOKE_FAIL stack=${STACK} reason=curl_error"
    return 1
  }
  echo "${resp}" | head -c 1500
  echo ""
  local sql rows
  sql=$(echo "${resp}" | jq -r '.sql // empty')
  rows=$(echo "${resp}" | jq -r '.rows | length // 0')
  if [ -z "${sql}" ] || [ "${rows}" = "0" ] || [ "${rows}" = "null" ]; then
    echo "NL_SMOKE_FAIL stack=${STACK} reason=empty_sql_or_rows"
    return 1
  fi
  echo "NL_SMOKE_OK stack=${STACK} sql_len=${#sql} rows=${rows}"
  return 0
}

simple_db_smoke || exit 1

case "${STACK}" in
  langchain|dbgpt)
    if [ "${SKIP_NL_SMOKE:-false}" != "true" ]; then
      if [ "${STACK}" = "langchain" ]; then
        simple_nl_smoke_api 8011 || exit 1
      elif [ "${STACK}" = "dbgpt" ]; then
        simple_nl_smoke_api 8012 || exit 1
      fi
    else
      echo "NL_SMOKE_SKIP stack=${STACK}"
    fi
    ;;
  premsql|vanna|wrenai)
    echo "NL_SMOKE_SKIP stack=${STACK} (UI stack: health + DB_SMOKE only; no harness)"
    ;;
  chat2db)
    echo "NL_SMOKE_SKIP stack=${STACK} (UI: health + DB; configure Custom AI in UI for NL2SQL)"
    ;;
esac

exit 0

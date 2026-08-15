#!/bin/bash
set -uxo pipefail
BUCKET="${PACKAGE_BUCKET:?}"
PREFIX="${PACKAGE_PREFIX:-doris-test/package}"
VERSION="${PACKAGE_VERSION:?}"
OLLAMA_BASE="${OLLAMA_HOST:?}"
DORIS_HOST="${DORIS_FE_HOST:?}"
LLM_BACKEND="${LLM_BACKEND:-ollama}"
VLLM_BASE="${VLLM_BASE_URL:-$OLLAMA_BASE}"
PRIMARY_MODEL="${OLLAMA_PRIMARY_MODEL:-Snowflake/Arctic-Text2SQL-R1-7B}"
ARCTIC_DIALECT="${ARCTIC_SQL_DIALECT:-mysql}"
DB_BACKEND="${DB_BACKEND:-doris}"
SQL_EXEC_MODE="${SQL_EXEC_MODE:-skip}"
BIRD_PG_HOST_VAL="${BIRD_PG_HOST:-}"

dnf install -y docker awscli || true
systemctl enable docker && systemctl start docker
rm -rf /home/ec2-user/doris-test && mkdir -p /home/ec2-user/doris-test
aws s3 cp "s3://${BUCKET}/${PREFIX}/${VERSION}/package.tgz" /tmp/doris-test.tgz
tar -xzf /tmp/doris-test.tgz -C /home/ec2-user/doris-test

cd /home/ec2-user/doris-test/compose
cp -f ../env.aws.example .env
{
  echo "OLLAMA_HOST=${OLLAMA_BASE}"
  echo "VLLM_BASE_URL=${VLLM_BASE}"
  echo "LLM_BACKEND=${LLM_BACKEND}"
  echo "DORIS_FE_HOST=${DORIS_HOST}"
  echo "DORIS_DATABASE=bird_minidev_olap"
  echo "OLLAMA_PRIMARY_MODEL=${PRIMARY_MODEL}"
  echo "OLLAMA_FALLBACK_MODEL=${PRIMARY_MODEL}"
  echo "ARCTIC_SQL_DIALECT=${ARCTIC_DIALECT}"
  echo "ARCTIC_SQL_FENCE_PREFILL=true"
  echo "SQL_EXEC_MODE=${SQL_EXEC_MODE}"
  echo "DB_BACKEND=${DB_BACKEND}"
  echo "OLLAMA_NUM_PREDICT=${OLLAMA_NUM_PREDICT:-512}"
  echo "LLM_HTTP_TIMEOUT_SEC=${LLM_HTTP_TIMEOUT_SEC:-20}"
  echo "SQL_REPAIR_MAX_RETRIES=0"
  echo "NL2SQL_FAST_MODE=true"
  echo "SCHEMA_SOURCE=${SCHEMA_SOURCE:-bird_tables}"
  echo "BIRD_TABLES_JSON=${BIRD_TABLES_JSON:-/app/data/dev_tables.json}"
  echo "SCHEMA_SELECTOR_MODE=${SCHEMA_SELECTOR_MODE:-bm25}"
  echo "SCHEMA_BM25_INCLUDE_FK=${SCHEMA_BM25_INCLUDE_FK:-true}"
  echo "SCHEMA_FINAL_TOP_K=${SCHEMA_FINAL_TOP_K:-8}"
  if [ "${DB_BACKEND}" = "postgres" ]; then
    echo "DB_ID_AS_SCHEMA=${DB_ID_AS_SCHEMA:-false}"
  else
    echo "DB_ID_AS_SCHEMA=${DB_ID_AS_SCHEMA:-true}"
  fi
} >> .env

if [ "${DB_BACKEND}" = "postgres" ]; then
  if [ -z "${BIRD_PG_HOST_VAL}" ]; then
    echo "DB_BACKEND=postgres requires BIRD_PG_HOST" >&2
    exit 1
  fi
  {
    echo "DB_DIALECT=postgresql"
    echo "DB_URI=postgresql+psycopg://olap:olap@${BIRD_PG_HOST_VAL}:5432/bird"
    echo "ARCTIC_SQL_DIALECT=${ARCTIC_DIALECT:-postgresql}"
  } >> .env
else
  {
    echo "DB_DIALECT=mysql"
    echo "DB_URI=mysql+pymysql://root@${DORIS_HOST}:9030/bird_minidev_olap"
  } >> .env
fi

docker network create doris-test-net 2>/dev/null || true
# Compose file lives under stacks/; pass --env-file so DB_URI (analytics IP) is not lost
# to the doris-fe default in docker-compose.yml.
mkdir -p stacks/langchain
cp -f .env stacks/langchain/.env
docker compose --env-file .env -f stacks/langchain/docker-compose.yml up -d --build
# Allow API import/schema warmup before health probe
for i in $(seq 1 36); do
  if curl -sf "http://127.0.0.1:8011/healthz"; then
    echo
    echo "NL2SQL_SMOKE_OK backend=${LLM_BACKEND} db=${DB_BACKEND} dialect=${ARCTIC_DIALECT} uri_host=${DORIS_HOST}"
    exit 0
  fi
  sleep 5
done
echo "NL2SQL healthz failed" >&2
docker logs --tail 80 doris-test-langchain-langchain-api-1 >&2 || true
exit 1

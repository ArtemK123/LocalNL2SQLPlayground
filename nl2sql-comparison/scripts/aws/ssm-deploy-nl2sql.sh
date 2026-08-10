#!/bin/bash
# Bootstrap NL2SQL EC2: Docker + compose v2 + package from S3. Does NOT start Ollama locally.
set -uxo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
BUCKET="${BIRD_DATASET_BUCKET:?set BIRD_DATASET_BUCKET (e.g. nl2sql-comparison-bird-<account-id>)}"
VERSION="${BIRD_DATASET_VERSION:-2026-05-24}"
DB_IP="${BIRD_PG_HOST:?set BIRD_PG_HOST}"
OLLAMA_BASE="${OLLAMA_HOST:?set OLLAMA_HOST}"
LLM_BACKEND="${LLM_BACKEND:-ollama}"
VLLM_BASE="${VLLM_BASE_URL:-$OLLAMA_BASE}"
PRIMARY_MODEL="${OLLAMA_PRIMARY_MODEL:-arctic-text2sql-r1-7b:q4_k_m}"
NUM_PREDICT="${OLLAMA_NUM_PREDICT:-512}"
ARCTIC_PREFILL="${ARCTIC_SQL_FENCE_PREFILL:-true}"
LLM_HTTP_TIMEOUT="${LLM_HTTP_TIMEOUT_SEC:-20}"

install_compose() {
  mkdir -p /usr/local/lib/docker/cli-plugins
  if ! docker compose version >/dev/null 2>&1; then
    curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-$(uname -m)" \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  fi
}

dnf install -y docker awscli jq || true
systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user || true
install_compose
docker network inspect nl2sql-comparison-net >/dev/null 2>&1 \
  || docker network create nl2sql-comparison-net

rm -rf /home/ec2-user/nl2sql-comparison
mkdir -p /home/ec2-user/nl2sql-comparison
aws s3 cp "s3://${BUCKET}/nl2sql-comparison/bird/${VERSION}/package.tgz" /tmp/nl2sql.tgz
tar -xzf /tmp/nl2sql.tgz -C /home/ec2-user/nl2sql-comparison
chown -R ec2-user:ec2-user /home/ec2-user/nl2sql-comparison

cd /home/ec2-user/nl2sql-comparison/compose
cp -f ../env.aws.example .env
{
  echo "BIRD_PG_HOST=${DB_IP}"
  echo "OLLAMA_HOST=${OLLAMA_BASE}"
  echo "BIRD_PG_PORT=5432"
  echo "LLM_BACKEND=${LLM_BACKEND}"
  echo "VLLM_BASE_URL=${VLLM_BASE}"
  echo "OLLAMA_PRIMARY_MODEL=\"${PRIMARY_MODEL}\""
  echo "OLLAMA_FALLBACK_MODEL=\"${PRIMARY_MODEL}\""
  echo "OLLAMA_NUM_CTX=4096"
  echo "OLLAMA_NUM_PREDICT=${NUM_PREDICT}"
  echo "LLM_HTTP_TIMEOUT_SEC=${LLM_HTTP_TIMEOUT}"
  echo "ARCTIC_SQL_FENCE_PREFILL=${ARCTIC_PREFILL}"
  echo "ARCTIC_SQL_DIALECT=sqlite"
  echo "SCHEMA_SOURCE=bird_tables"
  echo "BIRD_TABLES_JSON=/app/data/dev_tables.json"
  echo "SCHEMA_FINAL_TOP_K=8"
  echo "SCHEMA_BM25_INCLUDE_FK=true"
  echo "SCHEMA_SELECTOR_MODE=bm25"
  echo "NL2SQL_FAST_MODE=true"
  echo "SQL_REPAIR_MAX_RETRIES=0"
  echo "SQL_EXEC_MODE=skip"
} >> .env

echo "NL2SQL_BOOTSTRAP_OK package=${VERSION} BIRD_PG_HOST=${DB_IP} LLM_BACKEND=${LLM_BACKEND} OLLAMA_HOST=${OLLAMA_BASE} VLLM_BASE_URL=${VLLM_BASE} OLLAMA_NUM_PREDICT=${NUM_PREDICT} ARCTIC_SQL_FENCE_PREFILL=${ARCTIC_PREFILL} SCHEMA_FINAL_TOP_K=8 SQL_EXEC_MODE=skip"
echo "Start a stack with smoke-aws-stack.ps1 or docker compose -f stacks/<name>/docker-compose.yml up -d --build"

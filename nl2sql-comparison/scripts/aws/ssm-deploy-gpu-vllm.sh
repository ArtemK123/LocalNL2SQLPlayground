#!/bin/bash
# Replace Ollama with vLLM (OpenAI-compatible) on the GPU host.
# Serves Snowflake/Arctic-Text2SQL-R1-7B on host :11434 (maps to container :8000).
# Capacity defaults target L4 24GB; harness workers are independent of this deploy.
set -uxo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
BUCKET="${BIRD_DATASET_BUCKET:?set BIRD_DATASET_BUCKET (e.g. nl2sql-comparison-bird-<account-id>)}"
VERSION="${BIRD_DATASET_VERSION:-2026-05-24}"
MAX_LEN="${VLLM_MAX_MODEL_LEN:-4096}"
GPU_UTIL="${VLLM_GPU_MEMORY_UTILIZATION:-0.90}"
MODEL="${VLLM_MODEL:-Snowflake/Arctic-Text2SQL-R1-7B}"
# Optional ops override only (empty = omit flag → vLLM engine default continuous batching).
MAX_SEQS="${VLLM_MAX_NUM_SEQS:-}"
ENFORCE_EAGER="${VLLM_ENFORCE_EAGER:-0}"

dnf install -y docker awscli jq || true
# Amazon Linux 2023 ships curl-minimal; do not install conflicting `curl` package.
command -v curl >/dev/null 2>&1 || dnf install -y curl-minimal || true
systemctl enable docker
systemctl start docker
docker network inspect nl2sql-comparison-net >/dev/null 2>&1 \
  || docker network create nl2sql-comparison-net
mkdir -p /usr/local/lib/docker/cli-plugins
if ! docker compose version >/dev/null 2>&1; then
  curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-$(uname -m)" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

rm -rf /home/ec2-user/nl2sql-comparison
mkdir -p /home/ec2-user/nl2sql-comparison
aws s3 cp "s3://${BUCKET}/nl2sql-comparison/bird/${VERSION}/package.tgz" /tmp/nl2sql.tgz
tar -xzf /tmp/nl2sql.tgz -C /home/ec2-user/nl2sql-comparison
chown -R ec2-user:ec2-user /home/ec2-user/nl2sql-comparison

cd /home/ec2-user/nl2sql-comparison/compose
cp -f ../env.aws.example .env
# Stop classic Ollama stack if present (frees GPU + port 11434 + disk for HF weights).
docker compose -f docker-compose.gpu.yml down || true
docker rm -f $(docker ps -aq --filter name=ollama) 2>/dev/null || true
# Reclaim Ollama model volume — vLLM uses vllm_hf_cache instead (L4 root disk is tight).
docker volume rm nl2sql-comparison-gpu_ollama_data 2>/dev/null || true
docker system prune -f || true
# Prune may delete the compose external network — recreate before up.
docker network inspect nl2sql-comparison-net >/dev/null 2>&1 \
  || docker network create nl2sql-comparison-net
# Stop any previous vLLM stack before recreate.
docker compose -f docker-compose.gpu.vllm.yml down || true

echo "DISK_AFTER_PRUNE"
df -h / | tail -1
docker system df || true

patch_env() {
  local key="$1"
  local val="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=\"${val}\"|" .env
  else
    echo "${key}=\"${val}\"" >> .env
  fi
}

patch_env LLM_BACKEND vllm
patch_env VLLM_MODEL "$MODEL"
patch_env VLLM_MAX_MODEL_LEN "$MAX_LEN"
patch_env VLLM_GPU_MEMORY_UTILIZATION "$GPU_UTIL"
patch_env VLLM_SERVED_MODEL_NAME "$MODEL"
patch_env OLLAMA_PRIMARY_MODEL "$MODEL"
patch_env OLLAMA_FALLBACK_MODEL "$MODEL"
patch_env OLLAMA_ACTIVE_MODEL "$MODEL"
if [ -n "$MAX_SEQS" ]; then
  patch_env VLLM_MAX_NUM_SEQS "$MAX_SEQS"
fi

export VLLM_MAX_MODEL_LEN="$MAX_LEN"
export VLLM_GPU_MEMORY_UTILIZATION="$GPU_UTIL"
export VLLM_MODEL="$MODEL"
export VLLM_SERVED_MODEL_NAME="$MODEL"

COMPOSE=docker-compose.gpu.vllm.yml
if ! grep -Fq "$MODEL" "$COMPOSE"; then
  sed -i "s|Snowflake/Arctic-Text2SQL-R1-7B|${MODEL}|g" "$COMPOSE"
fi

# Optional: inject --max-num-seqs / --enforce-eager without baking harness concurrency into the image.
EXTRA_ARGS=()
if [ -n "$MAX_SEQS" ]; then
  EXTRA_ARGS+=(--max-num-seqs "$MAX_SEQS")
fi
if [ "$ENFORCE_EAGER" = "1" ] || [ "$ENFORCE_EAGER" = "true" ]; then
  EXTRA_ARGS+=(--enforce-eager)
fi

docker compose -f "$COMPOSE" pull || true
if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then
  # Compose command is static; append via docker run override after compose create is awkward.
  # Prefer: rewrite command block by appending args in a one-shot override file.
  {
    echo "services:"
    echo "  vllm:"
    echo "    command:"
    echo "      - ${MODEL}"
    echo "      - --host"
    echo "      - \"0.0.0.0\""
    echo "      - --port"
    echo "      - \"8000\""
    echo "      - --max-model-len"
    echo "      - \"${MAX_LEN}\""
    echo "      - --gpu-memory-utilization"
    echo "      - \"${GPU_UTIL}\""
    echo "      - --dtype"
    echo "      - \"${VLLM_DTYPE:-auto}\""
    echo "      - --enable-prefix-caching"
    echo "      - --served-model-name"
    echo "      - \"${MODEL}\""
    for a in "${EXTRA_ARGS[@]}"; do
      echo "      - ${a}"
    done
  } > docker-compose.gpu.vllm.override.yml
  docker compose -f "$COMPOSE" -f docker-compose.gpu.vllm.override.yml up -d --force-recreate
else
  docker compose -f "$COMPOSE" up -d --force-recreate
fi

echo "Waiting for vLLM /v1/models (HF download + load can take 10–30+ min on cold host)..."
for i in $(seq 1 240); do
  if curl -sf http://127.0.0.1:11434/v1/models | grep -Eiq "arctic|Snowflake|${MODEL%%/*}"; then
    curl -sf http://127.0.0.1:11434/v1/models | head -c 2000
    echo
    echo "GPU_VLLM_SMOKE_OK model=$MODEL max_model_len=$MAX_LEN gpu_mem_util=$GPU_UTIL port=11434"
    exit 0
  fi
  CID=$(docker ps -aq --filter name=vllm | head -1 || true)
  if [ -n "${CID:-}" ]; then
    st=$(docker inspect -f '{{.State.Status}}/{{.State.ExitCode}}' "$CID" 2>/dev/null || true)
    echo "WAIT i=$i container=$st"
    docker logs --tail 8 "$CID" 2>&1 | tail -8 || true
  else
    echo "WAIT i=$i no_vllm_container"
  fi
  sleep 15
done
echo "GPU_VLLM_SMOKE_FAIL"
docker ps -a --filter name=vllm || true
docker compose -f "$COMPOSE" logs --tail 80 || true
exit 1

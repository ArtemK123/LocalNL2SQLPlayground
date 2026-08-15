#!/bin/bash
# Replace Ollama with vLLM on the doris-test GPU host (OpenAI-compatible :11434).
set -uxo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
BUCKET="${PACKAGE_BUCKET:?}"
PREFIX="${PACKAGE_PREFIX:-doris-test/package}"
VERSION="${PACKAGE_VERSION:?}"
MAX_LEN="${VLLM_MAX_MODEL_LEN:-4096}"
GPU_UTIL="${VLLM_GPU_MEMORY_UTILIZATION:-0.90}"
MODEL="${VLLM_MODEL:-Snowflake/Arctic-Text2SQL-R1-7B}"

dnf install -y docker awscli jq || true
command -v curl >/dev/null 2>&1 || dnf install -y curl-minimal || true
systemctl enable docker
systemctl start docker
docker network inspect doris-test-net >/dev/null 2>&1 || docker network create doris-test-net
mkdir -p /usr/local/lib/docker/cli-plugins
if ! docker compose version >/dev/null 2>&1; then
  curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-$(uname -m)" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

rm -rf /home/ec2-user/doris-test
mkdir -p /home/ec2-user/doris-test
aws s3 cp "s3://${BUCKET}/${PREFIX}/${VERSION}/package.tgz" /tmp/doris-test.tgz
tar -xzf /tmp/doris-test.tgz -C /home/ec2-user/doris-test
chown -R ec2-user:ec2-user /home/ec2-user/doris-test

cd /home/ec2-user/doris-test/compose
cp -f ../env.aws.example .env
docker compose -f docker-compose.gpu.yml down || true
docker rm -f $(docker ps -aq --filter name=ollama) 2>/dev/null || true
docker volume rm doris-test-gpu_ollama_data 2>/dev/null || true
docker system prune -f || true
docker network inspect doris-test-net >/dev/null 2>&1 || docker network create doris-test-net
docker compose -f docker-compose.gpu.vllm.yml down || true

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

export VLLM_MAX_MODEL_LEN="$MAX_LEN"
export VLLM_GPU_MEMORY_UTILIZATION="$GPU_UTIL"
export VLLM_MODEL="$MODEL"
export VLLM_SERVED_MODEL_NAME="$MODEL"

COMPOSE=docker-compose.gpu.vllm.yml
if ! grep -Fq "$MODEL" "$COMPOSE"; then
  sed -i "s|Snowflake/Arctic-Text2SQL-R1-7B|${MODEL}|g" "$COMPOSE"
fi

docker compose -f "$COMPOSE" pull || true
docker compose -f "$COMPOSE" up -d --force-recreate

echo "Waiting for vLLM /v1/models..."
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

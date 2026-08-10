#!/bin/bash
# Deploy Ollama on GPU EC2. Stages Q4 GGUF on the host (curl available), then create+warm.
set -uxo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
BUCKET="${BIRD_DATASET_BUCKET:?set BIRD_DATASET_BUCKET (e.g. nl2sql-comparison-bird-<account-id>)}"
VERSION="${BIRD_DATASET_VERSION:-2026-05-24}"
ACTIVE="${OLLAMA_ACTIVE_MODEL:-arctic-text2sql-r1-7b:q4_k_m}"
GGUF_NAME="Arctic-Text2SQL-R1-7B.Q4_K_M.gguf"
GGUF_URL="${OLLAMA_Q4_GGUF_URL:-https://huggingface.co/mradermacher/Arctic-Text2SQL-R1-7B-GGUF/resolve/main/${GGUF_NAME}}"
GGUF_CACHE="/opt/nl2sql-comparison/gguf"

dnf install -y docker awscli jq curl || true
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

# Stage Q4 GGUF on host (persists across package extract). ollama image has no curl.
mkdir -p "$GGUF_CACHE" /home/ec2-user/nl2sql-comparison/models/gguf
if [ ! -f "${GGUF_CACHE}/${GGUF_NAME}" ]; then
  echo "HOST_GGUF_DOWNLOAD url=$GGUF_URL"
  curl -fL --retry 5 --retry-delay 5 -o "${GGUF_CACHE}/${GGUF_NAME}.partial" "$GGUF_URL"
  mv "${GGUF_CACHE}/${GGUF_NAME}.partial" "${GGUF_CACHE}/${GGUF_NAME}"
fi
# Bind-mount cache into package path so compose ../models/gguf sees the GGUF.
if ! mountpoint -q /home/ec2-user/nl2sql-comparison/models/gguf; then
  mount --bind "$GGUF_CACHE" /home/ec2-user/nl2sql-comparison/models/gguf
fi
ls -lah /home/ec2-user/nl2sql-comparison/models/gguf/ | head -20

cd /home/ec2-user/nl2sql-comparison/compose
cp -f ../env.aws.example .env

patch_env() {
  local key="$1"
  local val="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=\"${val}\"|" .env
  else
    echo "${key}=\"${val}\"" >> .env
  fi
}

patch_env OLLAMA_ACTIVE_MODEL "$ACTIVE"
patch_env OLLAMA_SQL_MODEL "$ACTIVE"
patch_env OLLAMA_PRIMARY_MODEL "$ACTIVE"
patch_env OLLAMA_FALLBACK_MODEL "$ACTIVE"
# Concurrent generate slots (Ollama server); override via OLLAMA_NUM_PARALLEL env if needed.
if grep -q '^OLLAMA_NUM_PARALLEL=' .env; then
  sed -i "s|^OLLAMA_NUM_PARALLEL=.*|OLLAMA_NUM_PARALLEL=${OLLAMA_NUM_PARALLEL:-2}|" .env
else
  echo "OLLAMA_NUM_PARALLEL=${OLLAMA_NUM_PARALLEL:-2}" >> .env
fi

docker compose -f docker-compose.gpu.yml up -d --force-recreate
for i in $(seq 1 240); do
  if curl -sf http://127.0.0.1:11434/api/tags | grep -Fq "$ACTIVE"; then
    curl -sf http://127.0.0.1:11434/api/tags
    docker compose -f docker-compose.gpu.yml exec -T ollama ollama show "$ACTIVE" || true
    echo "GPU_SMOKE_OK active=$ACTIVE"
    exit 0
  fi
  # Surface create progress / crashes early
  CID=$(docker ps -aq --filter name=ollama | head -1 || true)
  if [ -n "${CID:-}" ]; then
    st=$(docker inspect -f '{{.State.Status}}/{{.State.ExitCode}}' "$CID" 2>/dev/null || true)
    echo "WAIT i=$i container=$st"
    docker logs --tail 5 "$CID" 2>&1 | tail -5 || true
  fi
  sleep 15
done
echo "GPU_SMOKE_FAIL active=$ACTIVE"
docker ps -a --filter name=ollama || true
exit 1

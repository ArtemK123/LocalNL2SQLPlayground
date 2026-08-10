#!/bin/bash
set -euxo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
BUCKET="${BIRD_DATASET_BUCKET:-YOUR_BIRD_DATASET_BUCKET}"
VERSION="${BIRD_DATASET_VERSION:-2026-05-25}"
TARGET="${OLLAMA_TARGET_MODEL:-qwen2.5-coder:14b-instruct-q8_0}"
COMPOSE_DIR="/home/ec2-user/nl2sql-comparison/compose"
ENV_FILE="${COMPOSE_DIR}/.env"
OLLAMA_URL="http://127.0.0.1:11434"

sudo dnf install -y docker awscli jq || true
sudo systemctl enable docker
sudo systemctl start docker

mkdir -p /usr/local/lib/docker/cli-plugins
if ! sudo docker compose version >/dev/null 2>&1; then
  sudo curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-$(uname -m)" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

sudo docker network inspect nl2sql-comparison-net >/dev/null 2>&1 \
  || sudo docker network create nl2sql-comparison-net

rm -rf /home/ec2-user/nl2sql-comparison
mkdir -p /home/ec2-user/nl2sql-comparison
aws s3 cp "s3://${BUCKET}/nl2sql-comparison/bird/${VERSION}/package.tgz" /home/ec2-user/nl2sql.tgz
tar -xzf /home/ec2-user/nl2sql.tgz -C /home/ec2-user/nl2sql-comparison
sudo chown -R ec2-user:ec2-user /home/ec2-user/nl2sql-comparison

cd "$COMPOSE_DIR"
cp -f ../env.aws.example .env
sudo docker compose -f docker-compose.gpu.yml up -d

for i in $(seq 1 60); do
  if curl -sf "${OLLAMA_URL}/api/tags" >/dev/null; then break; fi
  sleep 5
done

if ! curl -sf "${OLLAMA_URL}/api/tags" | grep -Fq "$TARGET"; then
  echo "Pulling model via API: $TARGET"
  curl -sf "${OLLAMA_URL}/api/pull" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"${TARGET}\",\"stream\":false}"
fi

echo "Warming model: $TARGET"
curl -sf "${OLLAMA_URL}/api/generate" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${TARGET}\",\"prompt\":\"hi\",\"stream\":false,\"options\":{\"num_predict\":1}}"

patch_env() {
  local key="$1"
  local val="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=\"${val}\"|" "$ENV_FILE"
  else
    echo "${key}=\"${val}\"" >> "$ENV_FILE"
  fi
}
patch_env OLLAMA_ACTIVE_MODEL "$TARGET"
patch_env OLLAMA_PRIMARY_MODEL "$TARGET"
patch_env OLLAMA_FALLBACK_MODEL "$TARGET"

curl -sf "${OLLAMA_URL}/api/tags" | grep -Fq "$TARGET"
sudo systemctl restart amazon-ssm-agent || true
echo "REMOTE_GPU_BOOTSTRAP_OK target=$TARGET"

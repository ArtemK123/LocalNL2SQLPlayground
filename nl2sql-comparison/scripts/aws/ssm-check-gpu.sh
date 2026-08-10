#!/bin/bash
# Read-only GPU + Docker profile checks on GPU EC2 host.
set -euo pipefail

echo "=== EC2 instance type ==="
curl -sf http://169.254.169.254/latest/meta-data/instance-type || echo "metadata unavailable"

echo ""
echo "=== nvidia-smi ==="
if command -v nvidia-smi &>/dev/null; then
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
  nvidia-smi -L
else
  echo "FAIL: nvidia-smi not found"
fi

echo ""
echo "=== Docker NVIDIA runtime ==="
docker info 2>/dev/null | grep -iE 'nvidia|runtime' || echo "(no nvidia lines in docker info)"

echo ""
echo "=== Compose GPU profile (deploy.resources) ==="
COMPOSE_DIR="/home/ec2-user/nl2sql-comparison/compose"
if [[ -d "$COMPOSE_DIR" ]]; then
  cd "$COMPOSE_DIR"
  docker compose -f docker-compose.gpu.yml config 2>/dev/null | grep -A8 'deploy:' || true
  docker compose -f docker-compose.gpu.yml config 2>/dev/null | grep -E 'nvidia|capabilities|driver' || echo "(no nvidia device lines in rendered config)"
else
  echo "WARN: $COMPOSE_DIR missing (deploy not run yet?)"
fi

echo ""
echo "=== Running Ollama container ==="
OLLAMA_CID="$(docker ps -q -f name=ollama 2>/dev/null | head -1)"
if [[ -n "$OLLAMA_CID" ]]; then
  docker ps -f name=ollama --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
  echo "--- DeviceRequests (expect Driver=nvidia, Capabilities=gpu) ---"
  docker inspect "$OLLAMA_CID" --format '{{json .HostConfig.DeviceRequests}}' | jq . 2>/dev/null || docker inspect "$OLLAMA_CID" --format '{{json .HostConfig.DeviceRequests}}'
  echo "--- Env NVIDIA_* ---"
  docker inspect "$OLLAMA_CID" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E '^NVIDIA_' || true
else
  echo "WARN: no running ollama container"
fi

echo ""
echo "=== Ollama API (models) ==="
curl -sf http://127.0.0.1:11434/api/tags | jq -r '.models[].name' 2>/dev/null || curl -sf http://127.0.0.1:11434/api/tags || echo "Ollama not reachable on :11434"

echo ""
echo "GPU_CHECK_DONE"

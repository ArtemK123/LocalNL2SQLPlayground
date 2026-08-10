#!/bin/bash
# Ensure nomic-embed-text is available on GPU Ollama (WrenAI embedder).
set -euo pipefail
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
EMBED="${OLLAMA_EMBEDDING_MODEL:-nomic-embed-text}"

if curl -sf "${OLLAMA_URL}/api/tags" | grep -Fq "${EMBED}"; then
  echo "EMBED_OK model=${EMBED} (already present)"
  exit 0
fi

echo "Pulling embedding model: ${EMBED}"
docker compose -f /home/ec2-user/nl2sql-comparison/compose/docker-compose.gpu.yml exec -T ollama ollama pull "${EMBED}"
curl -sf "${OLLAMA_URL}/api/tags" | grep -F "${EMBED}" || { echo "EMBED_PULL_FAIL"; exit 1; }
echo "EMBED_PULL_OK model=${EMBED}"

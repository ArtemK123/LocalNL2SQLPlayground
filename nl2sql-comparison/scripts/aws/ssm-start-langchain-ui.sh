#!/bin/bash
set -euo pipefail
cd /home/ec2-user/nl2sql-comparison/compose
docker compose --env-file .env -f stacks/langchain/docker-compose.yml --profile ui up -d --build chainlit
for i in $(seq 1 36); do
  if curl -sf http://127.0.0.1:8501 >/dev/null 2>&1; then
    echo "CHAINLIT_OK url=http://127.0.0.1:8501"
    exit 0
  fi
  sleep 5
done
echo "CHAINLIT_FAIL"
exit 1

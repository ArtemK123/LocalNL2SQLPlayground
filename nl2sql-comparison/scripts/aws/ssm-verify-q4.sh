#!/bin/bash
set -euxo pipefail
curl -sf http://127.0.0.1:11434/api/tags | tr -cd "\11\12\15\40-\176" | head -c 1500; echo
docker compose -f /home/ec2-user/nl2sql-comparison/compose/docker-compose.gpu.yml exec -T ollama ollama show arctic-text2sql-r1-7b:q4_k_m 2>&1 | tr -cd "\11\12\15\40-\176" | head -40
# patch active env
ENV=/home/ec2-user/nl2sql-comparison/compose/.env
sed -i "s|^OLLAMA_ACTIVE_MODEL=.*|OLLAMA_ACTIVE_MODEL=\"arctic-text2sql-r1-7b:q4_k_m\"|" "$ENV"
sed -i "s|^OLLAMA_PRIMARY_MODEL=.*|OLLAMA_PRIMARY_MODEL=\"arctic-text2sql-r1-7b:q4_k_m\"|" "$ENV"
grep -E "OLLAMA_(ACTIVE|PRIMARY|SQL)" "$ENV"
echo VERIFY_OK

#!/bin/bash
set -euxo pipefail
curl -sf http://127.0.0.1:8011/healthz
echo
CID=$(docker ps -q -f name=langchain-api | head -1)
echo CID=$CID
docker exec "$CID" python -c "from app import config; print(config.settings.ollama_primary_model, config.settings.ollama_num_predict, config.settings.schema_final_top_k)"
echo OK


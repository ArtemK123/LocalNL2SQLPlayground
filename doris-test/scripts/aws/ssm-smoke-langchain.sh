#!/bin/bash
set -euo pipefail
curl -sf http://127.0.0.1:8011/healthz
curl -sf -X POST http://127.0.0.1:8011/v1/chat -H 'Content-Type: application/json' \
  -d '{"question":"How many tables are visible?"}' | head -c 500
echo LANGCHAIN_SMOKE_OK

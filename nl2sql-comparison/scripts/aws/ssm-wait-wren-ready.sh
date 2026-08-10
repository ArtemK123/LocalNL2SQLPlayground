#!/bin/bash
# Wait for Wren bootstrap + semantics indexing, then smoke createAskingTask.
set -uo pipefail
cd /home/ec2-user/nl2sql-comparison/compose

echo "=== rendered config (batch + retrieval) ==="
docker run --rm -v nl2sql-comparison-wrenai_wren_rendered_config:/out alpine:3.19 \
  grep -E 'column_indexing_batch_size|table_retrieval|openai/' /out/config.yaml 2>/dev/null || true

echo ""
echo "=== wait bootstrapper (up to 45 min) ==="
for i in $(seq 1 270); do
  st=$(docker inspect -f '{{.State.Status}}' nl2sql-comparison-wrenai-wren-bootstrapper-1 2>/dev/null || echo missing)
  if [ "$st" = "exited" ]; then
    code=$(docker inspect -f '{{.State.ExitCode}}' nl2sql-comparison-wrenai-wren-bootstrapper-1 2>/dev/null || echo 1)
    docker logs nl2sql-comparison-wrenai-wren-bootstrapper-1 2>&1 | tail -5 | tr -cd '\11\12\15\40-\176'
    if [ "$code" = "0" ]; then echo "BOOTSTRAP_OK"; break; fi
    echo "BOOTSTRAP_FAIL exit=$code"; exit 1
  fi
  [ $((i % 6)) -eq 0 ] && echo "bootstrapper status=$st (${i}0s)"
  sleep 10
done

echo ""
echo "=== wait modelSync (up to 45 min) ==="
for i in $(seq 1 270); do
  resp=$(curl -s -X POST http://127.0.0.1:3001/api/graphql \
    -H 'Content-Type: application/json' \
    -d '{"query":"query { modelSync { status } }"}' | tr -cd '\11\12\15\40-\176')
  echo "$resp"
  if echo "$resp" | grep -qE 'SYNCHRONIZED|FINISHED'; then
    echo "MODEL_SYNC_OK"
    break
  fi
  if echo "$resp" | grep -q 'UNSYNCRONIZED' && [ "$i" -gt 120 ]; then
    echo "MODEL_SYNC_STILL_UNSYNC after 20min - checking ai logs"
    docker logs nl2sql-comparison-wrenai-wren-ai-service-1 2>&1 | tr -cd '\11\12\15\40-\176' | grep -iE 'semantics|fail|error' | tail -15
  fi
  sleep 10
done

echo ""
echo "=== createAskingTask smoke ==="
curl -s -X POST http://127.0.0.1:3001/api/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"mutation($q:String!){createAskingTask(data:{question:$q}){id}}","variables":{"q":"How many circuits are there?"}}' | tr -cd '\11\12\15\40-\176'
echo ""

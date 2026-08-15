#!/bin/sh
set -eu

ACTIVE="${OLLAMA_ACTIVE_MODEL:-${OLLAMA_PRIMARY_MODEL:-}}"

ollama serve &
OLLAMA_PID=$!

for i in $(seq 1 180); do
  if ollama list >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if [ -n "$ACTIVE" ]; then
  echo "Pulling active model: ${ACTIVE}"
  ollama pull "${ACTIVE}"
  echo "Warming active model: ${ACTIVE}"
  curl -sf "http://127.0.0.1:11434/api/generate" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"${ACTIVE}\",\"prompt\":\"hi\",\"stream\":false,\"options\":{\"num_predict\":1}}" \
    >/dev/null 2>&1 || echo "WARN: warm generate failed (model may still load on first request)"
fi

wait "$OLLAMA_PID"

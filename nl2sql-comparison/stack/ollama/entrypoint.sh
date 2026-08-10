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

ensure_model() {
  model="$1"
  case "$model" in
    arctic-text2sql-r1-7b:q4_k_m|*:q4_k_m)
      if [ -f /opt/nl2sql-ollama/ensure-arctic-q4.sh ]; then
        tr -d '\r' </opt/nl2sql-ollama/ensure-arctic-q4.sh >/tmp/ensure-arctic-q4.sh
        /bin/sh /tmp/ensure-arctic-q4.sh "$model"
      else
        echo "ERROR: Q4 ensure script missing for $model" >&2
        return 1
      fi
      ;;
    *)
      echo "Pulling active model: ${model}"
      ollama pull "${model}"
      ;;
  esac
}

if [ -n "$ACTIVE" ]; then
  # Keep ollama serve alive even if model bootstrap fails (exit 127 previously killed the container).
  if ! ensure_model "$ACTIVE"; then
    echo "WARN: ensure_model failed for $ACTIVE — server stays up for diagnosis" >&2
  else
    echo "Warming active model: ${ACTIVE}"
    # ollama image may lack curl; use API via ollama CLI when possible.
    ollama run "$ACTIVE" "hi" >/dev/null 2>&1 \
      || echo "WARN: warm failed (model may still load on first request)"
  fi
fi

wait "$OLLAMA_PID"

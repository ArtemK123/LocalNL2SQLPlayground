#!/bin/bash
# Switch GPU Ollama active catalog model (unload other text models, lazy pull, warm, patch .env).
# AWS only — invoked via ssm-set-gpu-model.sh on the GPU host.
set -euo pipefail

TARGET="${1:-}"
COMPOSE_DIR="${COMPOSE_DIR:-/home/ec2-user/nl2sql-comparison/compose}"
ENV_FILE="${COMPOSE_DIR}/.env"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"

if [ -z "$TARGET" ]; then
  echo "Usage: switch-model.sh <model-tag>" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

# Windows-published package.tgz can leave CRLF in compose/.env — strip before source.
# shellcheck disable=SC1090
set -a
# shellcheck source=/dev/null
source <(tr -d '\r' <"$ENV_FILE")
set +a

SQL_MODEL="${OLLAMA_SQL_MODEL:-arctic-text2sql-r1-7b:q4_k_m}"
GENERAL_MODEL="${OLLAMA_GENERAL_MODEL:-qwen2.5-coder:14b-instruct-q8_0}"

if [ "$TARGET" != "$SQL_MODEL" ] && [ "$TARGET" != "$GENERAL_MODEL" ]; then
  echo "Target must be catalog model: $SQL_MODEL or $GENERAL_MODEL (got: $TARGET)" >&2
  exit 1
fi

echo "Switching GPU active model to: $TARGET"

# Unload loaded text-generation models (keep embedding models).
if command -v jq >/dev/null 2>&1; then
  curl -sf "${OLLAMA_URL}/api/ps" | jq -r '.models[]?.name // empty' | while read -r name; do
    case "$name" in
      *embed*|nomic-embed-text) echo "Keeping embedding model loaded: $name" ;;
      *)
        echo "Unloading model: $name"
        curl -sf "${OLLAMA_URL}/api/generate" \
          -H "Content-Type: application/json" \
          -d "{\"model\":\"${name}\",\"prompt\":\"\",\"stream\":false,\"keep_alive\":0}" \
          >/dev/null 2>&1 || true
        ;;
    esac
  done
else
  echo "WARN: jq missing; skipping explicit unload"
fi

# Lazy pull / create if not present.
if ! curl -sf "${OLLAMA_URL}/api/tags" | grep -Fq "$TARGET"; then
  case "$TARGET" in
    arctic-text2sql-r1-7b:q4_k_m|*:q4_k_m)
      echo "Creating Q4 model: $TARGET"
      docker compose -f "${COMPOSE_DIR}/docker-compose.gpu.yml" exec -T ollama \
        /bin/sh -c 'tr -d "\r" </opt/nl2sql-ollama/ensure-arctic-q4.sh >/tmp/ensure-arctic-q4.sh && /bin/sh /tmp/ensure-arctic-q4.sh "'"$TARGET"'"' \
        > /tmp/ollama-pull.log 2>&1 &
      ;;
    *)
      echo "Pulling model: $TARGET"
      docker compose -f "${COMPOSE_DIR}/docker-compose.gpu.yml" exec -T ollama ollama pull "$TARGET" \
        > /tmp/ollama-pull.log 2>&1 &
      ;;
  esac
  pull_pid=$!
  while kill -0 "$pull_pid" 2>/dev/null; do
    echo "PULL_PROGRESS $(date -Is) target=$TARGET"
    tail -n 1 /tmp/ollama-pull.log 2>/dev/null || true
    sleep 30
  done
  if ! wait "$pull_pid"; then
    echo "PULL_FAIL: ensure/pull $TARGET" >&2
    tail -n 40 /tmp/ollama-pull.log >&2 || true
    exit 1
  fi
  echo "PULL_OK target=$TARGET"
fi

echo "Warming model: $TARGET"
curl -sf "${OLLAMA_URL}/api/generate" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${TARGET}\",\"prompt\":\"hi\",\"stream\":false,\"options\":{\"num_predict\":1}}" \
  >/dev/null

# Patch compose/.env — ACTIVE + backward-compat PRIMARY/FALLBACK.
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

# Smoke: tags + 1-token generate.
if ! curl -sf "${OLLAMA_URL}/api/tags" | grep -Fq "$TARGET"; then
  echo "SMOKE_FAIL: $TARGET not in /api/tags" >&2
  exit 1
fi
curl -sf "${OLLAMA_URL}/api/generate" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${TARGET}\",\"prompt\":\"1\",\"stream\":false,\"options\":{\"num_predict\":1}}" \
  >/dev/null

echo "SWITCH_OK active=$TARGET"
curl -sf "${OLLAMA_URL}/api/tags" | head -c 2000 || true

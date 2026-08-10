#!/bin/sh
# Create local Ollama tag arctic-text2sql-r1-7b:q4_k_m from a host-staged Q4_K_M GGUF.
# Runs inside the ollama container (no curl/wget in that image — stage on EC2 host first).
set -eu

TAG="${1:-${OLLAMA_Q4_TAG:-arctic-text2sql-r1-7b:q4_k_m}}"
GGUF_NAME="Arctic-Text2SQL-R1-7B.Q4_K_M.gguf"
STAGED="${OLLAMA_Q4_GGUF_PATH:-/models/gguf/${GGUF_NAME}}"
BUILD_DIR="${OLLAMA_Q4_BUILD_DIR:-/root/.ollama/arctic-q4-build}"
MODELFILE_SRC="${OLLAMA_Q4_MODELFILE:-/opt/nl2sql-ollama/Modelfile.arctic-q4_k_m}"
FORCE_RECREATE="${FORCE_ARCTIC_Q4_RECREATE:-0}"

if ollama list 2>/dev/null | grep -Fq "$TAG"; then
  if [ "$FORCE_RECREATE" = "1" ] || [ "$FORCE_RECREATE" = "true" ]; then
    echo "ARCTIC_Q4_RECREATE tag=$TAG"
    ollama rm "$TAG" || true
  else
    echo "ARCTIC_Q4_PRESENT tag=$TAG"
    exit 0
  fi
fi

if [ ! -f "$STAGED" ]; then
  echo "ARCTIC_Q4_MISSING staged GGUF not found at $STAGED" >&2
  echo "Host must download mradermacher Q4_K_M into models/gguf before compose up." >&2
  exit 1
fi

mkdir -p "$BUILD_DIR"
# Prefer hardlink/copy into writable ollama volume (FROM path must be readable for create).
if [ ! -f "${BUILD_DIR}/${GGUF_NAME}" ]; then
  echo "ARCTIC_Q4_STAGE from=$STAGED"
  ln "$STAGED" "${BUILD_DIR}/${GGUF_NAME}" 2>/dev/null \
    || cp -f "$STAGED" "${BUILD_DIR}/${GGUF_NAME}"
fi

cd "$BUILD_DIR"
if [ -f "$MODELFILE_SRC" ]; then
  sed "s|^FROM .*|FROM ${BUILD_DIR}/${GGUF_NAME}|" "$MODELFILE_SRC" > Modelfile
else
  cat > Modelfile <<EOF
FROM ${BUILD_DIR}/${GGUF_NAME}
SYSTEM """You are a data science expert. Below, you are provided with a database schema and a natural language question. Your task is to understand the schema and generate a valid SQL query to answer the question."""
PARAMETER temperature 0
PARAMETER num_predict 1024
EOF
fi

echo "ARCTIC_Q4_CREATE tag=$TAG"
ollama create "$TAG" -f Modelfile
echo "ARCTIC_Q4_OK tag=$TAG"
ollama show "$TAG" || true

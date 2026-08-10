#!/bin/bash
# Switch GPU Ollama active model on GPU EC2 via switch-model.sh.
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

TARGET="${OLLAMA_TARGET_MODEL:?OLLAMA_TARGET_MODEL required}"
ROOT="${NL2SQL_ROOT:-/home/ec2-user/nl2sql-comparison}"

if [ ! -d "$ROOT" ]; then
  echo "Package not found at $ROOT — run deploy-gpu-from-s3.ps1 first" >&2
  exit 1
fi

cd "$ROOT"
bash stack/ollama/switch-model.sh "$TARGET"

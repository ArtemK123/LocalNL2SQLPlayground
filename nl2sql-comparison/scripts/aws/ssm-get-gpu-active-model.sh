#!/bin/bash
# Read OLLAMA_ACTIVE_MODEL from GPU host compose/.env
set -euo pipefail
ENV="${COMPOSE_DIR:-/home/ec2-user/nl2sql-comparison/compose}/.env"
if [ ! -f "$ENV" ]; then
  echo "MISSING_ENV"
  exit 1
fi
if grep -q '^OLLAMA_ACTIVE_MODEL=' "$ENV"; then
  grep '^OLLAMA_ACTIVE_MODEL=' "$ENV" | head -1 | cut -d= -f2- | tr -d '"'
elif grep -q '^OLLAMA_PRIMARY_MODEL=' "$ENV"; then
  grep '^OLLAMA_PRIMARY_MODEL=' "$ENV" | head -1 | cut -d= -f2- | tr -d '"'
else
  echo "UNKNOWN"
  exit 1
fi

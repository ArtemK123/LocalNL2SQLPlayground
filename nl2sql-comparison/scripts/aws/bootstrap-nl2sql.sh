#!/bin/bash
# Run on NL2SQL EC2.

set -euo pipefail

dnf update -y
dnf install -y docker awscli jq
systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user || true
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${SCRIPT_DIR}/install-docker-compose-v2.sh"

echo "bootstrap-nl2sql.sh complete."
echo "Set compose/.env with BIRD_PG_HOST and OLLAMA_HOST (private IPs), then start one stack."

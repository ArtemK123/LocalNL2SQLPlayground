#!/bin/bash
# Run on GPU EC2 (DLAMI / g5.xlarge or g6.xlarge Spot).

set -euo pipefail

dnf update -y
dnf install -y docker awscli
systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user || true
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${SCRIPT_DIR}/install-docker-compose-v2.sh"

if ! command -v nvidia-smi &>/dev/null; then
  echo "nvidia-smi missing — install drivers per AWS DLAMI docs or reboot."
fi

curl -fsSL https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo \
  | tee /etc/yum.repos.d/nvidia-container-toolkit.repo
dnf install -y nvidia-container-toolkit || true
nvidia-ctk runtime configure --runtime=docker || true
systemctl restart docker || true

echo "bootstrap-gpu.sh complete."
echo "  cd compose && docker compose -f docker-compose.gpu.yml up -d"

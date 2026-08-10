#!/bin/bash
# Run on DB EC2 (Amazon Linux 2023). Terraform user-data mounts /data/postgres.

set -euo pipefail

dnf update -y
dnf install -y docker awscli jq
systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user || true
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${SCRIPT_DIR}/install-docker-compose-v2.sh"

mkdir -p /opt/nl2sql-comparison/bird-assets
echo "bootstrap-db.sh complete."
echo "From your laptop (do NOT scp BIRD_dev.sql to EC2):"
echo "  .\\scripts\\aws\\upload-bird-to-s3.ps1 -ReadBucketFromTfvars"
echo "  .\\scripts\\aws\\deploy-db-from-s3.ps1 -SkipUpload"
echo "Or one step: .\\scripts\\aws\\deploy-db-from-s3.ps1"

#!/bin/bash
# Bootstrap GPU Ollama when GPU SSM agent is unavailable (run on bastion via SSM).
set -euxo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

GPU_IP="${GPU_PRIVATE_IP:?set GPU_PRIVATE_IP}"
GPU_ID="${GPU_INSTANCE_ID:?set GPU_INSTANCE_ID}"
BUCKET="${BIRD_DATASET_BUCKET:-YOUR_BIRD_DATASET_BUCKET}"
VERSION="${BIRD_DATASET_VERSION:-2026-05-25}"
TARGET="${OLLAMA_TARGET_MODEL:-qwen2.5-coder:14b-instruct-q8_0}"
AZ="${GPU_AZ:-us-east-1a}"

KEY=/tmp/nl2sql-gpu-bootstrap
rm -f "$KEY" "$KEY.pub"
ssh-keygen -t rsa -f "$KEY" -N "" -q
aws ec2-instance-connect send-ssh-public-key \
  --instance-id "$GPU_ID" \
  --availability-zone "$AZ" \
  --instance-os-user ec2-user \
  --ssh-public-key "file://${KEY}.pub"

remote() {
  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 -i "$KEY" "ec2-user@${GPU_IP}" "$@"
}

remote 'echo GPU_SSH_OK'
remote 'sudo systemctl restart amazon-ssm-agent || true'
remote 'sudo dnf install -y docker awscli jq || true; sudo systemctl enable docker; sudo systemctl start docker'
remote 'mkdir -p /usr/local/lib/docker/cli-plugins'
remote 'if ! docker compose version >/dev/null 2>&1; then curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-$(uname -m)" -o /usr/local/lib/docker/cli-plugins/docker-compose && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose; fi'
remote "sudo docker network inspect nl2sql-comparison-net >/dev/null 2>&1 || sudo docker network create nl2sql-comparison-net"
remote "rm -rf /home/ec2-user/nl2sql-comparison && mkdir -p /home/ec2-user/nl2sql-comparison"
remote "aws s3 cp s3://${BUCKET}/nl2sql-comparison/bird/${VERSION}/package.tgz /tmp/nl2sql.tgz"
remote "tar -xzf /tmp/nl2sql.tgz -C /home/ec2-user/nl2sql-comparison && sudo chown -R ec2-user:ec2-user /home/ec2-user/nl2sql-comparison"
remote "cd /home/ec2-user/nl2sql-comparison/compose && cp -f ../env.aws.example .env && docker compose -f docker-compose.gpu.yml up -d"
remote 'for i in $(seq 1 60); do curl -sf http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 5; done'
remote "bash /home/ec2-user/nl2sql-comparison/stack/ollama/switch-model.sh '${TARGET}'"

echo "BASTION_GPU_BOOTSTRAP_OK target=${TARGET}"

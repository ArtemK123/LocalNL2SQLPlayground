#!/bin/bash
set -euxo pipefail
export AWS_DEFAULT_REGION=us-east-1
BUCKET="${BIRD_DATASET_BUCKET:?set BIRD_DATASET_BUCKET (e.g. nl2sql-comparison-bird-<account-id>)}"
VERSION="${BIRD_DATASET_VERSION:-2026-05-23}"
dnf install -y docker awscli jq || true
systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user || true
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-$(uname -m)" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
rm -rf /home/ec2-user/nl2sql-comparison
mkdir -p /home/ec2-user
aws s3 cp "s3://${BUCKET}/nl2sql-comparison/bird/${VERSION}/package.tgz" /tmp/nl2sql.tgz
tar -xzf /tmp/nl2sql.tgz -C /home/ec2-user
chown -R ec2-user:ec2-user /home/ec2-user/nl2sql-comparison
cd /home/ec2-user/nl2sql-comparison/compose
cp -f ../env.aws.example .env
docker compose -f docker-compose.db.aws.yml up -d
for i in $(seq 1 30); do
  docker exec bird-postgres pg_isready -U bird -d bird && break
  sleep 2
done
docker exec bird-postgres psql -U bird -d bird -c "SELECT 1 AS ok;"
TABLES=$(docker exec bird-postgres psql -U bird -d bird -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema');")
echo "TABLE_COUNT=${TABLES}"
echo DB_SMOKE_OK

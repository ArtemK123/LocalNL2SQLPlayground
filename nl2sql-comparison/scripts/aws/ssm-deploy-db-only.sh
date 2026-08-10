#!/bin/bash
# Deploy DB stack on DB EC2 via SSM. Package from S3; BIRD dataset from S3 (never from laptop).
set -uxo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

BUCKET="${BIRD_DATASET_BUCKET:?set BIRD_DATASET_BUCKET (e.g. nl2sql-comparison-bird-<account-id>)}"
PREFIX="${BIRD_DATASET_PREFIX:-nl2sql-comparison/bird}"
VERSION="${BIRD_DATASET_VERSION:-2026-05-24}"
PACKAGE_VERSION="${PACKAGE_VERSION:-${VERSION}}"

dnf install -y docker awscli jq || true
systemctl enable docker
systemctl start docker
mkdir -p /usr/local/lib/docker/cli-plugins
if ! docker compose version >/dev/null 2>&1; then
  curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-$(uname -m)" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

rm -rf /home/ec2-user/nl2sql-comparison
mkdir -p /home/ec2-user/nl2sql-comparison /opt/nl2sql-comparison/bird-assets
aws s3 cp "s3://${BUCKET}/${PREFIX}/${PACKAGE_VERSION}/package.tgz" /tmp/nl2sql.tgz
tar -xzf /tmp/nl2sql.tgz -C /home/ec2-user/nl2sql-comparison
chown -R ec2-user:ec2-user /home/ec2-user/nl2sql-comparison

cd /home/ec2-user/nl2sql-comparison/compose
cp -f ../env.aws.example .env
{
  echo "BIRD_DATASET_BUCKET=${BUCKET}"
  echo "BIRD_DATASET_PREFIX=${PREFIX}"
  echo "BIRD_DATASET_VERSION=${VERSION}"
  echo "BIRD_DATASET_LOCAL_DIR=/opt/nl2sql-comparison/bird-assets"
} >> .env

docker compose -f docker-compose.db.aws.yml up -d
for i in $(seq 1 60); do
  docker exec bird-postgres pg_isready -U bird -d bird && break
  sleep 3
done

export NL2SQL_COMPARISON_ROOT=/home/ec2-user/nl2sql-comparison
bash "${NL2SQL_COMPARISON_ROOT}/scripts/aws/stage-bird-assets.sh"

TABLES=$(docker exec bird-postgres psql -U bird -d bird -tAc \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema');")
echo "TABLE_COUNT=${TABLES}"
docker exec bird-postgres psql -U bird -d bird -f /docker-entrypoint-initdb.d/smoke_queries.sql 2>/dev/null || true
echo DB_SMOKE_OK

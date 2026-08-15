#!/bin/bash
set -euxo pipefail
BUCKET="${PACKAGE_BUCKET:-doris-test-bird}"
VERSION="${PACKAGE_VERSION:-2026-06-01}"
PREFIX="${PACKAGE_PREFIX:-doris-test/package}"
dnf install -y docker awscli || true
systemctl enable docker && systemctl start docker
usermod -aG docker ec2-user || true
rm -rf /home/ec2-user/doris-test
mkdir -p /home/ec2-user
aws s3 cp "s3://${BUCKET}/${PREFIX}/${VERSION}/package.tgz" /tmp/doris-test.tgz
tar -xzf /tmp/doris-test.tgz -C /home/ec2-user
chown -R ec2-user:ec2-user /home/ec2-user/doris-test
cd /home/ec2-user/doris-test/compose
cp -f ../env.aws.example .env
docker compose -f docker-compose.db.aws.yml up -d
for i in $(seq 1 60); do docker exec bird-postgres pg_isready -U bird -d bird && break; sleep 2; done
if [ ! -f /data/postgres/.bird_loaded ]; then
  bash /home/ec2-user/doris-test/scripts/aws/stage-bird-assets.sh || true
  touch /data/postgres/.bird_loaded || true
fi
docker exec bird-postgres psql -U bird -d bird -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='formula_1';"
echo DB_DEPLOY_OK

#!/bin/bash
set -uxo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
BUCKET="${BIRD_DATASET_BUCKET:?}"
PREFIX="${BIRD_DATASET_PREFIX:-doris-test/package}"
VERSION="${BIRD_DATASET_VERSION:?}"
PACKAGE_VERSION="${PACKAGE_VERSION:-$VERSION}"

dnf install -y docker awscli jq || true
systemctl enable docker && systemctl start docker
mkdir -p /usr/local/lib/docker/cli-plugins
if ! docker compose version >/dev/null 2>&1; then
  curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-$(uname -m)" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

rm -rf /home/ec2-user/doris-test
mkdir -p /home/ec2-user/doris-test /opt/doris-test/bird-assets
aws s3 cp "s3://${BUCKET}/${PREFIX}/${PACKAGE_VERSION}/package.tgz" /tmp/doris-test.tgz
tar -xzf /tmp/doris-test.tgz -C /home/ec2-user/doris-test
chown -R ec2-user:ec2-user /home/ec2-user/doris-test

cd /home/ec2-user/doris-test/compose
cp -f ../env.aws.example .env
docker compose -f docker-compose.db.aws.yml up -d
for i in $(seq 1 60); do docker exec bird-postgres pg_isready -U bird -d bird && break; sleep 3; done

export DORIS_TEST_ROOT=/home/ec2-user/doris-test
bash "${DORIS_TEST_ROOT}/scripts/aws/stage-bird-assets.sh"
echo DB_SMOKE_OK

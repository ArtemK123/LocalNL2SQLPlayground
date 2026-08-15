#!/bin/bash
set -uxo pipefail
BUCKET="${PACKAGE_BUCKET:?}"
PREFIX="${PACKAGE_PREFIX:-doris-test/package}"
VERSION="${PACKAGE_VERSION:?}"
dnf install -y docker awscli nvidia-container-toolkit || true
systemctl enable docker && systemctl start docker
rm -rf /home/ec2-user/doris-test && mkdir -p /home/ec2-user/doris-test
aws s3 cp "s3://${BUCKET}/${PREFIX}/${VERSION}/package.tgz" /tmp/doris-test.tgz
tar -xzf /tmp/doris-test.tgz -C /home/ec2-user/doris-test
cd /home/ec2-user/doris-test/compose
cp -f ../env.aws.example .env
docker compose -f docker-compose.gpu.yml up -d --build
echo GPU_SMOKE_OK

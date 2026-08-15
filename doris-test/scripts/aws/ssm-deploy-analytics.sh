#!/bin/bash
set -uxo pipefail
BUCKET="${PACKAGE_BUCKET:?}"
PREFIX="${PACKAGE_PREFIX:-doris-test/package}"
VERSION="${PACKAGE_VERSION:?}"
bash /home/ec2-user/doris-test/scripts/bootstrap-analytics.sh 2>/dev/null || sysctl -w vm.max_map_count=2000000

dnf install -y docker awscli || true
systemctl enable docker && systemctl start docker
rm -rf /home/ec2-user/doris-test && mkdir -p /home/ec2-user/doris-test
aws s3 cp "s3://${BUCKET}/${PREFIX}/${VERSION}/package.tgz" /tmp/doris-test.tgz
tar -xzf /tmp/doris-test.tgz -C /home/ec2-user/doris-test

cd /home/ec2-user/doris-test/compose
cp -f ../env.aws.example .env
{
  echo "BIRD_PG_HOST=${BIRD_PG_HOST:?}"
  echo "BIRD_PG_USER=${BIRD_PG_USER:-debezium}"
  echo "BIRD_PG_PASSWORD=${BIRD_PG_PASSWORD:-debezium}"
  echo "DORIS_FE_HOST=doris-fe"
  echo "DORIS_DATABASE=bird_minidev_olap"
} >> .env

docker network create doris-test-net 2>/dev/null || true
docker compose -f docker-compose.analytics.yml -f docker-compose.analytics.aws.yml up -d --remove-orphans
# Ensure Doris FE/BE healthy, then reset OLAP DB + force-run init with latest SQL artifacts.
for i in $(seq 1 60); do
  docker compose -f docker-compose.analytics.yml -f docker-compose.analytics.aws.yml ps doris-be --format '{{.Status}}' 2>/dev/null | grep -qi healthy && break
  sleep 5
done
docker run --rm --network doris-test-doris-internal mysql:8.4 \
  mysql -h172.29.0.10 -P9030 -uroot -e "DROP DATABASE IF EXISTS bird_minidev_olap; DROP DATABASE IF EXISTS california_schools; DROP DATABASE IF EXISTS card_games; DROP DATABASE IF EXISTS codebase_community; DROP DATABASE IF EXISTS debit_card_specializing; DROP DATABASE IF EXISTS european_football_2; DROP DATABASE IF EXISTS financial; DROP DATABASE IF EXISTS formula_1; DROP DATABASE IF EXISTS student_club; DROP DATABASE IF EXISTS superhero; DROP DATABASE IF EXISTS thrombosis_prediction; DROP DATABASE IF EXISTS toxicology;" || true
docker compose -f docker-compose.analytics.yml -f docker-compose.analytics.aws.yml up -d --force-recreate --no-deps doris-init
# Wait for doris-init one-shot (CDC snapshot + ODS load can take a long time)
for i in $(seq 1 360); do
  st=$(docker compose -f docker-compose.analytics.yml -f docker-compose.analytics.aws.yml ps doris-init --format '{{.Status}}' 2>/dev/null || true)
  echo "doris-init status: ${st}"
  echo "$st" | grep -qi "exited (0)" && break
  echo "$st" | grep -qi "exited ([1-9]" && {
    docker logs --tail 80 doris-test-analytics-doris-init-1 || true
    exit 1
  }
  sleep 15
done
docker compose -f docker-compose.analytics.yml -f docker-compose.analytics.aws.yml ps
echo ANALYTICS_DEPLOY_OK

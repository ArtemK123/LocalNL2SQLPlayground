#!/bin/bash
# Register Postgres connections in Chat2DB via REST API (bootstrap profile).
set -uxo pipefail
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
DB_IP="${BIRD_PG_HOST:?set BIRD_PG_HOST}"

cd /home/ec2-user/nl2sql-comparison/compose
if [ ! -f .env ]; then
  cp -f ../env.aws.example .env
fi
grep -q '^BIRD_PG_HOST=' .env || echo "BIRD_PG_HOST=${DB_IP}" >> .env
sed -i "s|^BIRD_PG_HOST=.*|BIRD_PG_HOST=${DB_IP}|" .env

docker compose --env-file .env --profile bootstrap -f stacks/chat2db/docker-compose.yml run --rm chat2db-seed
echo CHAT2DB_SEED_OK

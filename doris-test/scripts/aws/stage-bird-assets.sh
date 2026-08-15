#!/bin/bash
set -euo pipefail
MARKER="/data/postgres/.bird_loaded"
BUCKET="${BIRD_DATASET_BUCKET:?}"
PREFIX="${BIRD_DATASET_PREFIX:-doris-test/package}"
VERSION="${BIRD_DATASET_VERSION:?}"
LOCAL_DIR="${BIRD_DATASET_LOCAL_DIR:-/opt/doris-test/bird-assets}"

if [ -f "$MARKER" ]; then
  echo "BIRD already loaded ($MARKER)"
  exit 0
fi

mkdir -p "$LOCAL_DIR"
aws s3 cp "s3://${BUCKET}/${PREFIX}/${VERSION}/BIRD_dev.sql" "${LOCAL_DIR}/BIRD_dev.sql"
docker exec -i bird-postgres psql -U bird -d bird < "${LOCAL_DIR}/BIRD_dev.sql"
docker exec bird-postgres bash /docker-entrypoint-initdb.d/z99_grants.sh || true
docker exec bird-postgres psql -U bird -d bird -f /docker-entrypoint-initdb.d/z99_publications.sql 2>/dev/null || true
touch "$MARKER"
echo "BIRD load complete"

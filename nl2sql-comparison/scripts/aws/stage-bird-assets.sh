#!/bin/bash
# Download BIRD from S3 and load into bird-postgres if not already loaded on EBS.

set -uxo pipefail

ROOT="${NL2SQL_COMPARISON_ROOT:-/home/ec2-user/nl2sql-comparison}"
COMPOSE_DIR="${ROOT}/compose"
MARKER="/data/postgres/.bird_loaded"

if [[ -f "${COMPOSE_DIR}/.env" ]]; then
  # shellcheck disable=SC1091
  source "${COMPOSE_DIR}/.env"
fi

: "${BIRD_DATASET_BUCKET:?Set BIRD_DATASET_BUCKET}"
: "${BIRD_DATASET_PREFIX:?Set BIRD_DATASET_PREFIX}"
: "${BIRD_DATASET_VERSION:?Set BIRD_DATASET_VERSION}"
: "${BIRD_DATASET_LOCAL_DIR:?Set BIRD_DATASET_LOCAL_DIR}"

if [[ -f "${MARKER}" ]]; then
  echo "BIRD already loaded (${MARKER}); skipping S3 load."
  exit 0
fi

S3_URI="s3://${BIRD_DATASET_BUCKET}/${BIRD_DATASET_PREFIX}/${BIRD_DATASET_VERSION}"
LOCAL_DIR="${BIRD_DATASET_LOCAL_DIR}"
SQL_PATH="${LOCAL_DIR}/BIRD_dev.sql"

mkdir -p "${LOCAL_DIR}"
echo "Downloading BIRD from ${S3_URI} -> ${LOCAL_DIR}"
aws s3 sync "${S3_URI}" "${LOCAL_DIR}" --exact-timestamps
if ! aws s3 ls "${S3_URI}/BIRD_dev.sql" >/dev/null 2>&1; then
  echo "ERROR: ${S3_URI}/BIRD_dev.sql not found in S3."
  echo "On your laptop run: .\\scripts\\aws\\upload-bird-to-s3.ps1 -Bucket ${BIRD_DATASET_BUCKET} -Version ${BIRD_DATASET_VERSION}"
  exit 1
fi

if [[ -f "${LOCAL_DIR}/manifest.sha256" ]]; then
  (cd "${LOCAL_DIR}" && sha256sum -c manifest.sha256)
fi

if [[ ! -f "${SQL_PATH}" ]]; then
  echo "Missing ${SQL_PATH}"
  exit 1
fi

PG_CONTAINER="$(docker ps --filter name=bird-postgres --format '{{.Names}}' | head -n1)"
if [[ -z "${PG_CONTAINER}" ]]; then
  echo "bird-postgres not running. Start docker-compose.db.aws.yml first."
  exit 1
fi

echo "Loading BIRD_dev.sql into ${PG_CONTAINER}..."
cat "${SQL_PATH}" | docker exec -i "${PG_CONTAINER}" psql -U "${BIRD_PG_USER:-bird}" -d "${BIRD_PG_DB:-bird}" >/tmp/bird_load.log
docker exec "${PG_CONTAINER}" /bin/sh /docker-entrypoint-initdb.d/z99_grants.sh
touch "${MARKER}"
echo "BIRD load complete; marker ${MARKER} created."

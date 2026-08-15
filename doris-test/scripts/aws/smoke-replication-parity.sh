#!/bin/bash
# Compare row counts PG (DB host) vs Doris ODS for a sample schema.
set -euo pipefail
SCHEMA="${1:-formula_1}"
PG_HOST="${BIRD_PG_HOST:-bird-postgres}"
DORIS_HOST="${DORIS_FE_HOST:-127.0.0.1}"

tables=$(docker exec bird-postgres psql -U bird -d bird -tAc \
  "SELECT table_name FROM information_schema.tables WHERE table_schema='${SCHEMA}' AND table_type='BASE TABLE' ORDER BY 1 LIMIT 5")

for t in $tables; do
  pg_n=$(docker exec bird-postgres psql -U bird -d bird -tAc "SELECT COUNT(*) FROM ${SCHEMA}.\"${t}\"")
  ods="ods_${SCHEMA}_${t}"
  doris_n=$(mysql -h"$DORIS_HOST" -P9030 -uroot -N -e "SELECT COUNT(*) FROM bird_minidev_olap.\`${ods}\`" 2>/dev/null || echo "ERR")
  echo "${SCHEMA}.${t}: pg=${pg_n} doris=${doris_n}"
done

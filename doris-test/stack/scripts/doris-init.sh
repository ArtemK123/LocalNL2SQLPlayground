#!/usr/bin/env bash
set -euo pipefail

HOST="${DORIS_FE_HOST:-doris-fe}"
PORT="${DORIS_FE_QUERY_PORT:-9030}"
USER="${DORIS_ADMIN_USER:-root}"

echo "Waiting for Doris FE MySQL protocol on ${HOST}:${PORT}..."
for _ in $(seq 1 120); do
  if mysql -h "$HOST" -P "$PORT" -u"$USER" -e "SELECT 1" 2>/dev/null; then
    break
  fi
  sleep 2
done

echo "Extra wait for BE + Kafka topics..."
sleep 35

run_sql() {
  local f="$1"
  echo "Applying $(basename "$f")..."
  mysql -h "$HOST" -P "$PORT" -u"$USER" < "$f"
}

run_sql /doris/00_database.sql
run_sql /doris/10_ods_tables.sql
run_sql /doris/20_routine_loads.sql
run_sql /doris/30_seed_marts.sql
run_sql /doris/analytics_schema.sql

echo "Doris init finished successfully."

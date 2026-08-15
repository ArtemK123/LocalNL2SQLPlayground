#!/usr/bin/env bash
# Compare row counts PG vs Doris ODS for a schema (requires psql + mysql clients).
set -euo pipefail
PG_DSN="${PG_DSN:-postgresql://bird:bird@127.0.0.1:55432/bird}"
DORIS_DSN="${DORIS_DSN:-mysql://root@127.0.0.1:9030/bird_minidev_olap}"
SCHEMA="${1:-formula_1}"
echo "Parity check for schema $SCHEMA (sample tables)"

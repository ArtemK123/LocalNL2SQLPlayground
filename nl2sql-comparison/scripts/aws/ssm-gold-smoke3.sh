#!/bin/bash
set -euo pipefail
PG=$(docker ps --format '{{.Names}}' | grep -i postgres | head -1 || true)
if [ -z "$PG" ]; then echo "NO_PG_CONTAINER"; exit 1; fi
run() { docker exec -e PGPASSWORD=bird "$PG" psql -U bird -d bird -tAc "$1" 2>&1 || echo FAIL; }
echo "Q847:"
run "SELECT T2.surname FROM qualifying AS T1 INNER JOIN drivers AS T2 ON T2.driverId = T1.driverId WHERE T1.raceId = 19 ORDER BY T1.q2 ASC NULLS FIRST LIMIT 1"
echo "Q850:"
run "SELECT DISTINCT T2.name FROM circuits AS T1 INNER JOIN races AS T2 ON T2.circuitID = T1.circuitId WHERE T1.country = 'Germany'"
echo "Q854:"
run "SELECT DISTINCT T1.lat, T1.lng FROM circuits AS T1 INNER JOIN races AS T2 ON T2.circuitID = T1.circuitId WHERE T2.name = 'Australian Grand Prix'"

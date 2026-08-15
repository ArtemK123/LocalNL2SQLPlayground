#!/bin/sh
set -eu
# Load every *.sql under /docker-entrypoint-initdb.d/seed in sorted order.
# Point BIRD_MINIDEV_HOST_DIR (host) at your minidev export or drop .sql files into bird_db/seed/.

SEED_DIR="/docker-entrypoint-initdb.d/seed"
if [ ! -d "$SEED_DIR" ]; then
  echo "No seed dir at $SEED_DIR"
  exit 0
fi

found=0
# shellcheck disable=SC2012
for f in $(ls -1 "$SEED_DIR"/*.sql 2>/dev/null | sort); do
  found=1
  echo "battleground bird_db: loading $f"
  psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -f "$f"
done

if [ "$found" -eq 0 ]; then
  echo "battleground bird_db: no *.sql files in $SEED_DIR (database stays empty except roles)."
fi

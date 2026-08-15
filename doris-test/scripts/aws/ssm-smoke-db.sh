#!/bin/bash
set -euxo pipefail
docker exec bird-postgres pg_isready -U bird -d bird
docker exec bird-postgres psql -U bird -d bird -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='formula_1';"
echo DB_SMOKE_OK

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
py -3 -m pip install psycopg pymysql -q 2>$null
python (Join-Path $root "scripts\codegen\generate_cdc.py") --pg-dsn "postgresql://bird:bird@127.0.0.1:55432/bird" --pg-host bird-postgres
$compose = Join-Path $root "compose"
Push-Location $compose
if (-not (Test-Path ".env")) { Copy-Item "..\env.local.example" ".env" }
docker network create doris-test-net 2>$null
docker compose -f docker-compose.analytics.yml up -d
Pop-Location
Write-Host "Analytics stack starting (Kafka, Connect, Doris)."

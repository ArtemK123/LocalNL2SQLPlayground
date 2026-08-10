<#!
  Load formula_1-only BIRD seed (1-db / public schema) for local harness tests.
  Skips the full BIRD_dev.sql (~956 MB, 75 schemas). Use load_bird_dev.ps1 on AWS / full benchmarks.
#>
param(
    [string] $Container = "bird-postgres",
    [string] $PgUser = "bird",
    [string] $PgDatabase = "bird"
)

. "$PSScriptRoot\_common.ps1"
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Get-Nl2sqlComparisonRoot
$seedSql = Join-Path $root "stack\bird\seed\formula_1_seed.sql"
if (-not (Test-Path $seedSql)) {
    throw "formula_1 seed not found: $seedSql"
}

Write-Host "Resetting public schema and loading formula_1 seed (1-db) ..." -ForegroundColor Cyan
$resetSql = @"
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO public, bird, olap;
"@
$resetSql | docker exec -i $Container psql -U $PgUser -d $PgDatabase -v ON_ERROR_STOP=1
if ($LASTEXITCODE -ne 0) { throw "schema reset failed" }

Write-Host "Loading $seedSql (~14 MB) ..."
$cmd = "docker exec -i $Container psql -U $PgUser -d $PgDatabase -v ON_ERROR_STOP=1 < `"$seedSql`""
cmd.exe /c $cmd
if ($LASTEXITCODE -ne 0) { throw "formula_1 seed load failed" }

docker exec $Container /bin/sh /docker-entrypoint-initdb.d/z99_grants.sh
if ($LASTEXITCODE -ne 0) { throw "z99_grants.sh failed" }

$tableCount = docker exec $Container psql -U $PgUser -d $PgDatabase -tAc `
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
Write-Host "1-db load complete. public base tables: $($tableCount.Trim())"
Write-Host "Next: .\smoke-db.ps1 -Profile 1db" -ForegroundColor Green

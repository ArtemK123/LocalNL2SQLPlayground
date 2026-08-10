param(
    [ValidateSet("1db", "full")]
    [string] $Profile = "1db"
)

. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = "Stop"
$root = Get-Nl2sqlComparisonRoot
$queries = Join-Path $root "stack\bird\smoke_queries.sql"

docker exec bird-postgres psql -U bird -d bird -c "SELECT 1 AS ok;"
$publicCount = docker exec bird-postgres psql -U bird -d bird -tAc `
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
$totalCount = docker exec bird-postgres psql -U bird -d bird -tAc `
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema');"
Write-Host "Profile: $Profile | public base tables: $($publicCount.Trim()) | all schemas: $($totalCount.Trim())"

if ($Profile -eq "1db") {
    $pc = [int]$publicCount.Trim()
    if ($pc -lt 10) {
        throw "Expected >= 10 public tables after load_bird_1db.ps1 (got $pc). Run: .\load_bird_1db.ps1"
    }
    if ([int]$totalCount.Trim() -gt 25) {
        Write-Host "WARN: looks like full BIRD is loaded ($($totalCount.Trim()) tables). For local harness use load_bird_1db.ps1" -ForegroundColor Yellow
    }
} else {
    if ([int]$totalCount.Trim() -lt 50) {
        throw "Expected full BIRD (50+ tables). Run: .\load_bird_dev.ps1"
    }
}

Get-Content $queries | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("--")) {
        Write-Host "Running: $line"
        docker exec bird-postgres psql -U bird -d bird -c $line | Out-Host
    }
}
Write-Host "smoke-db: OK"

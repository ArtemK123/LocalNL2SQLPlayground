param([string] $DatasetsRoot = "")
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $DatasetsRoot) {
    $envFile = Join-Path $root "compose\.env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*DATASETS_ROOT=(.+)$') { $DatasetsRoot = $Matches[1].Trim(); break }
        }
    }
    if (-not $DatasetsRoot) { $DatasetsRoot = "..\..\datasets" }
}
$birdSql = Resolve-Path (Join-Path $root $DatasetsRoot "minidev\BIRD_dev\BIRD_dev.sql")
Write-Host "Loading $birdSql ..."
Get-Content $birdSql -Raw | docker exec -i bird-postgres psql -U bird -d bird
docker exec bird-postgres psql -U bird -d bird -f /docker-entrypoint-initdb.d/z99_publications.sql 2>$null
Write-Host "BIRD_dev load complete. Run: python scripts/codegen/generate_cdc.py"

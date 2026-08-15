$ErrorActionPreference = "Stop"
$compose = Join-Path $PSScriptRoot "..\..\compose"
Push-Location $compose
if (-not (Test-Path ".env")) { Copy-Item "..\env.local.example" ".env" }
docker compose -f docker-compose.db.yml up -d
Pop-Location
Write-Host "DB up on port 55432 (network doris-test-net)"

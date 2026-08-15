$ErrorActionPreference = "Stop"
$compose = Join-Path $PSScriptRoot "..\..\compose"
Push-Location $compose
if (-not (Test-Path ".env")) { Copy-Item "..\env.local.example" ".env" }
docker compose -f docker-compose.gpu.yml up -d
Pop-Location

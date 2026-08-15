$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
& (Join-Path $PSScriptRoot "up-db.ps1")
$compose = Join-Path $root "compose"
Push-Location (Join-Path $compose "stacks\langchain")
Copy-Item ..\..\env.local.example .env -Force -ErrorAction SilentlyContinue
docker compose up -d --build
Pop-Location
Write-Host "LangChain on http://127.0.0.1:8011"

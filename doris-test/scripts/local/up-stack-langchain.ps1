param([switch] $WithUI)
$ErrorActionPreference = "Stop"
$compose = Join-Path $PSScriptRoot "..\..\compose"
Push-Location $compose
docker network create doris-test-net 2>$null
$args = @("-f", "stacks/langchain/docker-compose.yml", "up", "-d", "--build")
if ($WithUI) { $args += "--profile"; $args += "ui" }
docker compose @args
Pop-Location
Write-Host "LangChain API http://127.0.0.1:8011/healthz"

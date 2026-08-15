$ErrorActionPreference = "Stop"
curl.exe -sf http://127.0.0.1:8011/healthz
curl.exe -sf http://127.0.0.1:8030/api/bootstrap
Write-Host "local smoke OK"

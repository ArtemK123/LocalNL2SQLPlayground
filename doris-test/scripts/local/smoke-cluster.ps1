$ErrorActionPreference = "Stop"
curl.exe -sf http://127.0.0.1:8011/healthz | Out-Null
Write-Host "LangChain healthz OK"
docker exec bird-postgres pg_isready -U bird -d bird
Write-Host "Postgres OK"
Write-Host "Run replication parity on analytics host after CDC snapshot completes."

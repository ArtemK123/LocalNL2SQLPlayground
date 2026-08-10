. "$PSScriptRoot\_common.ps1"
Invoke-Compose -ComposeFiles @("docker-compose.gpu.yml") -ComposeCommand @("up", "-d")
Write-Host "GPU up (pulls OLLAMA_PRIMARY_MODEL from compose/.env; local default qwen2.5:7b-instruct). Run smoke-gpu.ps1 when ready."

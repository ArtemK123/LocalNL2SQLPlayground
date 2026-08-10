. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = "Stop"
Ensure-ComposeEnv
$composeDir = Get-ComposeDir
Push-Location $composeDir
try {
    $port = 11434
    $expectedModel = "qwen2.5:7b-instruct"
    if (Test-Path ".env") {
        foreach ($line in Get-Content ".env") {
            if ($line -match '^\s*OLLAMA_PORT\s*=\s*(\d+)') { $port = [int]$Matches[1] }
            if ($line -match '^\s*OLLAMA_PRIMARY_MODEL\s*=\s*(.+)$') {
                $expectedModel = $Matches[1].Trim()
            }
        }
    }
    $tags = Invoke-RestMethod -Uri "http://127.0.0.1:${port}/api/tags" -TimeoutSec 30
    $names = ($tags.models | ForEach-Object { $_.name }) -join ", "
    Write-Host "Expected (local): $expectedModel"
    Write-Host "Models: $names"
    $needle = $expectedModel -replace '([\\.+^$|?*()[\]{}])', '\$1'
    if ($names -notmatch $needle) {
        Write-Warning "Expected model '$expectedModel' not in /api/tags yet (pull may still be running)."
    }
    Write-Host "smoke-gpu: OK (tags)"
}
finally {
    Pop-Location
}

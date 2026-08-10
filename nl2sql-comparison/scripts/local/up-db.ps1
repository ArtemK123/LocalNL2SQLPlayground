. "$PSScriptRoot\_common.ps1"
Invoke-Compose -ComposeFiles @("docker-compose.db.yml") -ComposeCommand @("up", "-d")
Write-Host "DB up."
Write-Host "  Local harness (1-db): .\load_bird_1db.ps1  (formula_1 in public; ~13 MB seed)" -ForegroundColor Cyan
Write-Host "  Full BIRD (AWS):      .\load_bird_dev.ps1   (all minidev schemas; ~956 MB)" -ForegroundColor DarkGray
Write-Host "Next: up-gpu.ps1"

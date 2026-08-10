$ErrorActionPreference = "Stop"

function Get-Nl2sqlComparisonRoot {
    $scriptDir = Split-Path -Parent $PSScriptRoot
    return (Resolve-Path (Join-Path $scriptDir "..")).Path
}

function Get-ComposeDir {
    return (Join-Path (Get-Nl2sqlComparisonRoot) "compose")
}

function Ensure-ComposeEnv {
    $composeDir = Get-ComposeDir
    $envFile = Join-Path $composeDir ".env"
    $example = Join-Path (Get-Nl2sqlComparisonRoot) "env.local.example"
    if (-not (Test-Path $envFile)) {
        Copy-Item $example $envFile
        Write-Host "Created compose/.env from env.local.example"
    }
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $ComposeFiles,
        [string[]] $ComposeCommand = @("up", "-d")
    )
    Ensure-ComposeEnv
    $composeDir = Get-ComposeDir
    Push-Location $composeDir
    try {
        $fileArgs = $ComposeFiles | ForEach-Object { "-f", $_ }
        $cmd = @("compose") + $fileArgs + $ComposeCommand
        & docker @cmd
        if ($LASTEXITCODE -ne 0) { throw "docker compose failed ($LASTEXITCODE)" }
    }
    finally {
        Pop-Location
    }
}

function Get-DatasetsRoot {
    $root = Get-Nl2sqlComparisonRoot
    $envFile = Join-Path (Get-ComposeDir) ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*DATASETS_ROOT\s*=\s*(.+)$') {
                $val = $Matches[1].Trim()
                if ($val) {
                    $candidate = Join-Path $root $val
                    if (Test-Path $candidate) {
                        return (Resolve-Path $candidate).Path
                    }
                }
            }
        }
    }
    $default = Join-Path $root "..\..\datasets"
    if (Test-Path $default) {
        return (Resolve-Path $default).Path
    }
    throw @"
datasets/ not found at $default

Clone or link BIRD/minidev data under repo datasets/minidev/ (see battleground_local/bird_db/.env.example).
Set DATASETS_ROOT in compose/.env if your checkout uses a different path.
"@
}

function Resolve-BirdDevSqlPath {
    param(
        [string] $SqlPath,
        [string] $DatasetsRoot
    )
    if ($SqlPath) {
        if (-not (Test-Path $SqlPath)) { throw "BIRD_dev.sql not found: $SqlPath" }
        return (Resolve-Path -LiteralPath $SqlPath).Path
    }
    if (-not $DatasetsRoot) { $DatasetsRoot = Get-DatasetsRoot }
    $minidev = Join-Path $DatasetsRoot "minidev"
    if (-not (Test-Path $minidev)) {
        throw "minidev folder not found: $minidev (expected BIRD under datasets/minidev/)"
    }
    $candidates = @(
        (Join-Path $minidev "MINIDEV_postgresql\BIRD_dev.sql"),
        (Join-Path $minidev "BIRD_dev.sql"),
        (Join-Path $minidev "MINIDEV\BIRD_dev.sql")
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return (Resolve-Path -LiteralPath $path).Path }
    }
    $found = Get-ChildItem -Path $minidev -Recurse -Filter "BIRD_dev.sql" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.FullName }
    throw @"
BIRD_dev.sql not found under $minidev

Expected (typical): datasets/minidev/MINIDEV_postgresql/BIRD_dev.sql
Pass -SqlPath explicitly or set DATASETS_ROOT in compose/.env.
"@
}

function Get-WrenMinidevSchemasCsv {
    return "california_schools,card_games,codebase_community,debit_card_specializing,european_football_2,financial,formula_1,student_club,superhero,thrombosis_prediction,toxicology"
}

function Set-WrenMinidevDeployEnv {
    $env:WREN_TARGET_TABLES = "*"
    $env:WREN_TARGET_SCHEMAS = Get-WrenMinidevSchemasCsv
}

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("langchain", "dbgpt", "premsql", "vanna", "wrenai", "chat2db")]
    [string] $Stack,
    [string] $Suite = "smoke_3",
    [string] $Dsn = "postgresql://olap:olap@127.0.0.1:55432/bird",
    [switch] $WithUI,
    [switch] $Headed,
    [switch] $SkipHealth,
    [ValidateSet("1db", "full")]
    [string] $DbProfile = "1db",
    [string] $Out,
    [double] $Timeout = 420,
    [int] $Limit = 0
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$root = Get-Nl2sqlComparisonRoot
$harness = Join-Path $root "harness"

function Get-HarnessPythonVersion {
    foreach ($ver in @("-3.13", "-3.12", "-3.11", "-3.10")) {
        try {
            & py $ver -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $ver }
        } catch { }
    }
    throw "Python 3.10+ required for nl2sql-harness (e.g. py -3.13)."
}

function Test-HarnessCli {
    $script:HarnessPythonVer = Get-HarnessPythonVersion
    & py $script:HarnessPythonVer -m pip show nl2sql-comparison-harness 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing harness (editable) with py $($script:HarnessPythonVer) ..."
        & py $script:HarnessPythonVer -m pip install -e "${harness}[ui]"
        if ($LASTEXITCODE -ne 0) { throw "pip install harness failed" }
    }
}

if (-not $SkipHealth) {
    Write-Host "=== smoke-db ($DbProfile) ===" -ForegroundColor Cyan
    & "$PSScriptRoot\smoke-db.ps1" -Profile $DbProfile
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "smoke-db failed" }
    Write-Host "=== smoke-stack: $Stack ===" -ForegroundColor Cyan
    & "$PSScriptRoot\smoke-stack.ps1" -Stack $Stack
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "smoke-stack failed" }
}

if ($WithUI -and $Stack -eq "langchain") {
    Write-Host "Ensure langchain stack includes Chainlit UI profile (up-stack -WithUI)." -ForegroundColor Yellow
}

Test-HarnessCli
$pyVer = $script:HarnessPythonVer

$runArgs = @(
    "run",
    "--framework", $Stack,
    "--suite", $Suite,
    "--dsn", $Dsn,
    "--resources", "local_docker",
    "--trace"
)

if ($Headed) { $runArgs += "--headed" }
if ($Out) { $runArgs += @("--out", $Out) }
$runArgs += @("--timeout", [string]$Timeout)
if ($Limit -gt 0) { $runArgs += @("--limit", [string]$Limit) }

$stackContainerMap = @{
    langchain = "nl2sql-comparison-langchain-langchain-api-1"
    dbgpt     = "nl2sql-comparison-dbgpt-dbgpt-webserver-1"
    premsql   = "nl2sql-comparison-premsql-premsql-api-1"
    vanna     = "nl2sql-comparison-vanna-vanna-api-1"
    wrenai    = "nl2sql-comparison-wrenai-wren-ui-1"
    chat2db   = "nl2sql-comparison-chat2db-chat2db-1"
}
if ($stackContainerMap.ContainsKey($Stack)) {
    $runArgs += @("--stack-containers", $stackContainerMap[$Stack])
}

Write-Host "=== nl2sql-harness $($runArgs -join ' ') ===" -ForegroundColor Cyan
Push-Location $harness
try {
    & py $pyVer -m nl2sql_comparison_harness @runArgs
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "nl2sql-harness failed ($LASTEXITCODE)" }
}
finally {
    Pop-Location
}

Write-Host "Done. Summarize with: nl2sql-harness summarize harness/runs/<file>.jsonl --table" -ForegroundColor Green

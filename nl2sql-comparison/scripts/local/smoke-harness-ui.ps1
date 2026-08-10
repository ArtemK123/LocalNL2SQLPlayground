param(
    [ValidateSet("langchain", "dbgpt", "premsql", "vanna", "wrenai", "chat2db")]
    [string[]] $Stacks = @("langchain", "dbgpt", "premsql", "vanna", "wrenai", "chat2db"),
    [switch] $Ask,
    [switch] $Headed,
    [switch] $SkipStack,
    [switch] $Build,
    [double] $Timeout = 120
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
    throw "Python 3.10+ required for nl2sql-harness."
}

$pyVer = Get-HarnessPythonVersion
& py $pyVer -m pip show nl2sql-comparison-harness 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    & py $pyVer -m pip install -e "${harness}[ui]"
}

$results = @()
foreach ($stack in $Stacks) {
    Write-Host "`n=== harness smoke-ui: $stack ===" -ForegroundColor Cyan
    if (-not $SkipStack) {
        if ($stack -eq "wrenai") {
            Set-WrenMinidevDeployEnv
            Write-Host "WREN_TARGET_TABLES=* WREN_TARGET_SCHEMAS=minidev (11 schemas)"
        }
        $upParams = @{ Stack = $stack }
        if ($Build) { $upParams.Build = $true }
        if ($stack -eq "langchain") { $upParams.WithUI = $true }
        if ($stack -eq "chat2db") { $upParams.Bootstrap = $true }
        & "$PSScriptRoot\up-stack.ps1" @upParams
        if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "up-stack $stack failed" }
        & "$PSScriptRoot\smoke-stack.ps1" -Stack $stack
        if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "smoke-stack $stack failed" }
    }

    $cliArgs = @("smoke-ui", "--framework", $stack, "--timeout", [string]$Timeout)
    if ($Ask) { $cliArgs += "--ask" }
    if ($Headed) { $cliArgs += "--headed" }
    Push-Location $harness
    try {
        & py $pyVer -m nl2sql_comparison_harness @cliArgs
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    $ok = ($null -eq $code -or $code -eq 0)
    $results += [pscustomobject]@{ Stack = $stack; Ok = $ok; ExitCode = $code }

    if (-not $SkipStack) {
        $composeFile = Join-Path $root "compose\stacks\$stack\docker-compose.yml"
        $downArgs = @("down")
        if ($stack -eq "langchain") {
            Invoke-Compose -ComposeFiles @($composeFile) -ComposeCommand @("--profile", "ui", "down")
        } else {
            Invoke-Compose -ComposeFiles @($composeFile) -ComposeCommand @("down")
        }
    }
}

Write-Host "`n=== smoke-ui summary ===" -ForegroundColor Green
$results | Format-Table -AutoSize
$failed = $results | Where-Object { -not $_.Ok }
if ($failed) { exit 1 }
exit 0

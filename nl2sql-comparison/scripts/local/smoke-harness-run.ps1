param(
    [ValidateSet("langchain", "dbgpt", "premsql", "vanna", "wrenai", "chat2db")]
    [string[]] $Stacks = @("langchain", "dbgpt", "premsql", "vanna", "wrenai", "chat2db"),
    [string] $Suite = "smoke_3",
    [int] $Limit = 1,
    [double] $Timeout = 180,
    [switch] $Build,
    [switch] $Headed
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$root = Get-Nl2sqlComparisonRoot
$harness = Join-Path $root "harness"
$pyVer = & {
    foreach ($ver in @("-3.13", "-3.12", "-3.11", "-3.10")) {
        & py $ver -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return $ver }
    }
    throw "Python 3.10+ required"
}

$results = @()
foreach ($stack in $Stacks) {
    Write-Host "`n=== harness run (limit=$Limit): $stack ===" -ForegroundColor Cyan
    if ($stack -eq "wrenai") {
        Set-WrenMinidevDeployEnv
    }
    $upParams = @{ Stack = $stack }
    if ($Build) { $upParams.Build = $true }
    if ($stack -eq "langchain") { $upParams.WithUI = $true }
    if ($stack -eq "chat2db") { $upParams.Bootstrap = $true }
    & "$PSScriptRoot\up-stack.ps1" @upParams
    & "$PSScriptRoot\smoke-stack.ps1" -Stack $stack
    Start-Sleep -Seconds $(if ($stack -eq "wrenai") { 15 } elseif ($stack -eq "langchain") { 5 } else { 2 })
    $benchParams = @{
        Stack      = $stack
        Suite      = $Suite
        DbProfile  = "full"
        Limit      = $Limit
        Timeout    = $Timeout
        SkipHealth = $true
    }
    if ($Headed) { $benchParams.Headed = $true }
    & "$PSScriptRoot\run-benchmark.ps1" @benchParams
    $code = $LASTEXITCODE
    $latest = Get-ChildItem (Join-Path $harness "runs") -Filter "${stack}_${Suite}_*.jsonl" |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $summary = $null
    if ($latest) {
        $summary = & py $pyVer -m nl2sql_comparison_harness summarize $latest.FullName 2>&1 | Out-String
    }
    $composeFile = Join-Path $root "compose\stacks\$stack\docker-compose.yml"
    if ($stack -eq "langchain") {
        Invoke-Compose -ComposeFiles @($composeFile) -ComposeCommand @("--profile", "ui", "down")
    } else {
        Invoke-Compose -ComposeFiles @($composeFile) -ComposeCommand @("down")
    }
    $results += [pscustomobject]@{
        Stack    = $stack
        Ok       = ($null -eq $code -or $code -eq 0)
        Jsonl    = if ($latest) { $latest.Name } else { "" }
        Summary  = ($summary -split "`n" | Select-Object -First 8) -join "`n"
    }
}

Write-Host "`n=== smoke-harness-run summary ===" -ForegroundColor Green
$results | Format-List
if ($results | Where-Object { -not $_.Ok }) { exit 1 }
exit 0

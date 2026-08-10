<#
.SYNOPSIS
  On-demand LangChain stack status (remote SSM + optional local port-forward checks).

.EXAMPLE
  .\scripts\aws\status-langchain.ps1

.EXAMPLE
  .\scripts\aws\status-langchain.ps1 -CheckLocal
#>
param(
    [string] $Region,
    [switch] $CheckLocal,
    [switch] $SkipCluster,
    [int] $TimeoutSec = 180
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
. "$PSScriptRoot\_experiment-common.ps1"
Ensure-AwsCli
$Region = Get-AwsRegion -Region $Region

if (-not $SkipCluster) {
    & (Join-Path $PSScriptRoot "ensure-cluster.ps1") -Region $Region | Out-Null
}

$targets = Resolve-ClusterTargets -Region $Region -RequireNl2sql -RequireGpu
$exitCode = 0

Write-Host "=== LangChain remote status (NL2SQL host) ===" -ForegroundColor Cyan
$inv = & (Join-Path $PSScriptRoot "invoke-ssm.ps1") `
    -InstanceId $targets.Nl2sqlInstanceId `
    -ScriptPath (Join-Path $PSScriptRoot "ssm-status-langchain.sh") `
    -Region $Region `
    -TimeoutSec $TimeoutSec `
    -AllowNonZeroExit

$stdout = [string]$inv.StandardOutputContent
if ($stdout -match "LANGCHAIN_STATUS=(\w+)") {
    switch ($Matches[1]) {
        "healthy" { }
        "degraded" { $exitCode = [Math]::Max($exitCode, 1) }
        "down" { $exitCode = 2 }
    }
}
if ($inv.Status -ne "Success" -and $stdout -notmatch "LANGCHAIN_STATUS=") {
    $exitCode = 2
}

Write-Host ""
Write-Host "=== GPU model (LangChain expects Arctic/sql) ===" -ForegroundColor Cyan
try {
    $gpuModel = & (Join-Path $PSScriptRoot "get-gpu-active-model.ps1") -GpuInstanceId $targets.GpuInstanceId -Region $Region -TimeoutSec 90
    Write-Host "OLLAMA_ACTIVE_MODEL=$gpuModel"
    $expected = (Get-StackModelsConfig)["langchain"]
    if ($expected -eq "sql" -and $gpuModel -notmatch "Arctic|arctic") {
        Write-Host "WARN GPU model is not Arctic; LangChain SQL quality/latency may differ." -ForegroundColor Yellow
        $exitCode = [Math]::Max($exitCode, 1)
    }
}
catch {
    Write-Host "FAIL GPU model read: $_" -ForegroundColor Red
    $exitCode = [Math]::Max($exitCode, 1)
}

if ($CheckLocal) {
    Write-Host ""
    Write-Host "=== Local port-forward checks ===" -ForegroundColor Cyan
    foreach ($entry in @(
            @{ Name = "langchain-api"; Port = 8011; Path = "/healthz" }
            @{ Name = "chainlit-ui"; Port = 8501; Path = "/" }
        )) {
        $port = $entry.Port
        $open = Test-LocalTcpPort -Port $port
        if (-not $open) {
            Write-Host "---- $($entry.Name) 127.0.0.1:${port} (no local tunnel)" -ForegroundColor DarkYellow
            Write-Host "     Start: .\scripts\aws\port-forward-ui.ps1 -Stack langchain  # UI :8501"
            Write-Host "     API :8011 needs a separate forward or experiment tunnels."
            continue
        }
        try {
            $uri = "http://127.0.0.1:${port}$($entry.Path)"
            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            $resp = Invoke-WebRequest -Uri $uri -TimeoutSec 15 -UseBasicParsing
            $sw.Stop()
            Write-Host "OK   $($entry.Name) $uri -> HTTP $($resp.StatusCode) ($($sw.ElapsedMilliseconds)ms)"
        }
        catch {
            Write-Host "FAIL $($entry.Name) 127.0.0.1:${port} ($($_.Exception.Message))" -ForegroundColor Red
            $exitCode = [Math]::Max($exitCode, 1)
        }
    }

    $tunnelState = Join-Path $env:TEMP "nl2sql-ui-forward-langchain.json"
    if (Test-Path $tunnelState) {
        $st = Get-Content $tunnelState -Raw | ConvertFrom-Json
        $alive = Get-Process -Id $st.pid -ErrorAction SilentlyContinue
        Write-Host "UI tunnel state: pid=$($st.pid) mode=$($st.mode) alive=$([bool]$alive)"
    }
}

Write-Host ""
Write-Host "=== Notes ===" -ForegroundColor Cyan
Write-Host "- /v1/chat with Arctic typically takes 90-120s; healthz stays OK while a query runs."
Write-Host "- Chainlit SQLite threads/steps errors => rebuild chainlit image and recreate the UI container/volume."
Write-Host "- Full API smoke (3 questions): scripts/aws/ssm-smoke-langchain-api-3q.sh (allow 10+ min)."

Write-Host ""
switch ($exitCode) {
    0 { Write-Host "LANGCHAIN_VERDICT=healthy" -ForegroundColor Green }
    1 { Write-Host "LANGCHAIN_VERDICT=degraded" -ForegroundColor Yellow }
    default { Write-Host "LANGCHAIN_VERDICT=down" -ForegroundColor Red }
}
exit $exitCode

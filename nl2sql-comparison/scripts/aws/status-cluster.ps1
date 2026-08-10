<#
.SYNOPSIS
  On-demand AWS cluster status: EC2 roles, GPU model, DB/NL2SQL application health.

.EXAMPLE
  .\scripts\aws\status-cluster.ps1

.EXAMPLE
  .\scripts\aws\status-cluster.ps1 -SkipRemote
#>
param(
    [string] $Region,
    [switch] $SkipRemote,
    [switch] $Quiet,
    [int] $TimeoutSec = 180
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
. "$PSScriptRoot\_experiment-common.ps1"
Ensure-AwsCli
$Region = Get-AwsRegion -Region $Region

Write-Host "=== EC2 instances ===" -ForegroundColor Cyan
$states = Get-ClusterInstanceStates -Region $Region
$states | Format-Table Role, State, PrivateIp, InstanceId, Ready -AutoSize

$bad = @($states | Where-Object { $_.Required -and -not $_.Ready })
if ($bad.Count -gt 0) {
    Write-Host "CLUSTER_VERDICT=down (EC2 not ready)" -ForegroundColor Red
    exit 2
}

if ($SkipRemote) {
    Write-Host "CLUSTER_VERDICT=ec2_ok (remote checks skipped)" -ForegroundColor Yellow
    exit 0
}

$targets = Resolve-ClusterTargets -Region $Region -RequireDb -RequireGpu -RequireNl2sql
$exitCode = 0

Write-Host ""
Write-Host "=== GPU active model ===" -ForegroundColor Cyan
try {
    $gpuModel = & (Join-Path $PSScriptRoot "get-gpu-active-model.ps1") -GpuInstanceId $targets.GpuInstanceId -Region $Region -TimeoutSec 90
    Write-Host "OLLAMA_ACTIVE_MODEL=$gpuModel"
    Write-Host "STATUS gpu_active_model=$gpuModel"
}
catch {
    Write-Host "FAIL GPU model read: $_" -ForegroundColor Red
    $exitCode = [Math]::Max($exitCode, 1)
}

Write-Host ""
Write-Host "=== DB host ===" -ForegroundColor Cyan
$dbInv = & (Join-Path $PSScriptRoot "invoke-ssm.ps1") `
    -InstanceId $targets.DbInstanceId `
    -ScriptPath (Join-Path $PSScriptRoot "ssm-status-cluster.sh") `
    -Region $Region `
    -Env @{ STATUS_ROLE = "db" } `
    -TimeoutSec $TimeoutSec `
    -AllowNonZeroExit
if ($dbInv.Status -ne "Success") { $exitCode = 2 }

Write-Host ""
Write-Host "=== NL2SQL host ===" -ForegroundColor Cyan
$nlInv = & (Join-Path $PSScriptRoot "invoke-ssm.ps1") `
    -InstanceId $targets.Nl2sqlInstanceId `
    -ScriptPath (Join-Path $PSScriptRoot "ssm-status-cluster.sh") `
    -Region $Region `
    -Env @{ STATUS_ROLE = "nl2sql" } `
    -TimeoutSec $TimeoutSec `
    -AllowNonZeroExit
if ($nlInv.Status -ne "Success") { $exitCode = 2 }

$stdout = [string]$nlInv.StandardOutputContent
if ($stdout -match "CLUSTER_STATUS=(\w+)") {
    switch ($Matches[1]) {
        "down" { $exitCode = 2 }
        "degraded" { $exitCode = [Math]::Max($exitCode, 1) }
    }
}

Write-Host ""
switch ($exitCode) {
    0 { Write-Host "CLUSTER_VERDICT=healthy" -ForegroundColor Green }
    1 { Write-Host "CLUSTER_VERDICT=degraded" -ForegroundColor Yellow }
    default { Write-Host "CLUSTER_VERDICT=down" -ForegroundColor Red }
}
if (-not $Quiet) {
    Write-Host ""
    Write-Host "Tip: .\scripts\aws\status-langchain.ps1 for LangChain-specific checks + local tunnels."
}
exit $exitCode

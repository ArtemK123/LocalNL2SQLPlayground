<#
.SYNOPSIS
  Query OLLAMA_ACTIVE_MODEL configured on the GPU EC2 host.
#>
param(
    [string] $GpuInstanceId,
    [string] $Region,
    [int] $TimeoutSec = 120
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
Ensure-AwsCli
$Region = Get-AwsRegion -Region $Region
$targets = Resolve-ClusterTargets -GpuInstanceId $GpuInstanceId -Region $Region -RequireGpu -RequireDb:$false -RequireNl2sql:$false

$inv = & (Join-Path $PSScriptRoot "invoke-ssm.ps1") `
    -InstanceId $targets.GpuInstanceId `
    -ScriptPath (Join-Path $PSScriptRoot "ssm-get-gpu-active-model.sh") `
    -Region $Region `
    -TimeoutSec $TimeoutSec

$stdout = [string]$inv.StandardOutputContent
$line = ($stdout -split "`n" | Where-Object { $_ -match '\S' } | Select-Object -Last 1)
if (-not $line -or $line -eq "MISSING_ENV" -or $line -eq "UNKNOWN") {
    throw "Could not read GPU active model from $($targets.GpuInstanceId): $line"
}
return $line.Trim()

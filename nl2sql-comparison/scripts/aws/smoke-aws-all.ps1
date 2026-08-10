<#
.SYNOPSIS
  Run health smokes for all six NL2SQL frameworks on AWS (one at a time via SSM).
#>
param(
    [string[]] $Stacks = @("langchain", "dbgpt", "premsql", "vanna", "wrenai", "chat2db"),
    [switch] $SkipGpuDeploy,
    [switch] $SkipPublish,
    [string] $Region,
    [int] $StackTimeoutSec = 7200
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
Ensure-AwsCli
$Region = Get-AwsRegion -Region $Region
Ensure-ClusterInstances -Region $Region -RequireDb -RequireGpu -RequireNl2sql
$targets = Resolve-ClusterTargets -Region $Region

if (-not $SkipGpuDeploy) {
    & (Join-Path $PSScriptRoot "deploy-gpu-from-s3.ps1") -Region $Region -SkipPublish:$SkipPublish
}

$results = @()
foreach ($stack in $Stacks) {
    Write-Host "`n=== AWS smoke: $stack ==="
    try {
        & (Join-Path $PSScriptRoot "smoke-aws-stack.ps1") `
            -Stack $stack `
            -Region $Region `
            -SkipPublish:$SkipPublish `
            -TimeoutSec $StackTimeoutSec
        $results += [pscustomobject]@{ Stack = $stack; Status = "OK" }
    }
    catch {
        Write-Warning "Stack $stack failed: $_"
        $results += [pscustomobject]@{ Stack = $stack; Status = "FAIL"; Error = $_.Exception.Message }
    }
}

$results | Format-Table -AutoSize
$failed = @($results | Where-Object { $_.Status -ne "OK" })
if ($failed.Count -gt 0) {
    throw "$($failed.Count) stack(s) failed: $($failed.Stack -join ', ')"
}
Write-Host "All $($results.Count) AWS stack smokes passed."

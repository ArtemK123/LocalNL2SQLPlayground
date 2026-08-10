<#
.SYNOPSIS
  Switch the active catalog model on the AWS GPU Ollama host (manual runtime switch).

.DESCRIPTION
  Unloads the other text-generation model, lazy-pulls the target if needed, warms it,
  and patches GPU compose/.env (OLLAMA_ACTIVE_MODEL + PRIMARY/FALLBACK).

  Use -ModelProfile sql (Arctic) or general (Qwen) before stack deploy/benchmark.
  Chat2DB and dbgpt require general; other SQL stacks require sql.

.EXAMPLE
  .\scripts\aws\set-gpu-model.ps1 -ModelProfile general

.EXAMPLE
  .\scripts\aws\set-gpu-model.ps1 -Model qwen2.5-coder:14b-instruct-q8_0
#>
param(
    [ValidateSet("sql", "general")]
    [string] $ModelProfile,
    [string] $Model,
    [string] $GpuInstanceId,
    [string] $Region,
    [int] $TimeoutSec = 1800
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_experiment-common.ps1"
Ensure-AwsCli
$Region = Get-AwsRegion -Region $Region
Ensure-ClusterInstances -Region $Region -RequireGpu -RequireDb:$false -RequireNl2sql:$false
$targets = Resolve-ClusterTargets -GpuInstanceId $GpuInstanceId -Region $Region -RequireGpu -RequireDb:$false -RequireNl2sql:$false

$catalog = Get-OllamaModelCatalog
$targetModel = if ($Model) {
    $Model
} elseif ($ModelProfile -eq "general") {
    $catalog.general
} elseif ($ModelProfile -eq "sql") {
    $catalog.sql
} else {
    throw "Specify -ModelProfile sql|general or -Model <ollama-tag>"
}

if ($targetModel -ne $catalog.sql -and $targetModel -ne $catalog.general) {
    throw "Model must be catalog entry: $($catalog.sql) or $($catalog.general) (got: $targetModel)"
}

Write-Host "Switching GPU Ollama on $($targets.GpuInstanceId) to: $targetModel"

& (Join-Path $PSScriptRoot "invoke-ssm.ps1") `
    -InstanceId $targets.GpuInstanceId `
    -ScriptPath (Join-Path $PSScriptRoot "ssm-set-gpu-model.sh") `
    -Region $Region `
    -Env @{
        OLLAMA_TARGET_MODEL = $targetModel
        AWS_DEFAULT_REGION  = $Region
    } `
    -TimeoutSec $TimeoutSec

$active = & (Join-Path $PSScriptRoot "get-gpu-active-model.ps1") -GpuInstanceId $targets.GpuInstanceId -Region $Region
Write-Host "GPU active model: $active" -ForegroundColor Green

<#
.SYNOPSIS
  Deploy vLLM (OpenAI-compatible) on the doris-test GPU EC2 host for Arctic Text2SQL.
  Serves on host :11434 (container :8000).
#>
param(
    [string] $GpuInstanceId,
    [string] $Bucket,
    [string] $Version,
    [string] $Region,
    [string] $Model = "Snowflake/Arctic-Text2SQL-R1-7B",
    [int] $MaxModelLen = 4096,
    [double] $GpuMemoryUtilization = 0.90,
    [switch] $SkipPublish,
    [int] $TimeoutSec = 7200
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
Ensure-AwsCli
$Region = Get-AwsRegion -Region $Region
Ensure-ClusterInstances -Region $Region -Quiet
$cfg = Get-PackageDatasetConfig -Bucket $Bucket -Version $Version
$targets = Resolve-ClusterTargets -Region $Region
$gpuId = if ($GpuInstanceId) { $GpuInstanceId } else { $targets.GpuInstanceId }

if (-not $SkipPublish) {
    & "$PSScriptRoot\publish-package-to-s3.ps1" -Bucket $cfg.Bucket -Version $cfg.Version
}

Write-Host "Deploying GPU vLLM on $gpuId model=$Model"

& "$PSScriptRoot\invoke-ssm.ps1" `
    -InstanceId $gpuId `
    -ScriptPath (Join-Path $PSScriptRoot "ssm-deploy-gpu-vllm.sh") `
    -Region $Region `
    -Env @{
        PACKAGE_BUCKET              = $cfg.Bucket
        PACKAGE_PREFIX              = $cfg.Prefix
        PACKAGE_VERSION             = $cfg.Version
        VLLM_MODEL                  = $Model
        VLLM_MAX_MODEL_LEN          = "$MaxModelLen"
        VLLM_GPU_MEMORY_UTILIZATION = ("{0:F2}" -f $GpuMemoryUtilization)
        AWS_DEFAULT_REGION          = $Region
    } `
    -TimeoutSec $TimeoutSec

$vllmBase = if ($targets.GpuPrivateIp) { "http://$($targets.GpuPrivateIp):11434" } else { $null }
Write-Host "GPU vLLM deploy complete. VLLM_BASE_URL=$vllmBase (OpenAI /v1)"

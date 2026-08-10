<#
.SYNOPSIS
  Deploy vLLM (OpenAI-compatible) on the GPU EC2 host for Arctic Text2SQL.
  Serves on host :11434 (container :8000). Capacity defaults target L4 24GB;
  harness concurrency is controlled separately via experiment workers.
#>
param(
    [string] $GpuInstanceId,
    [string] $Bucket,
    [string] $Version,
    [string] $Region,
    [string] $Model = "Snowflake/Arctic-Text2SQL-R1-7B",
    # Optional ops override; omit (0) to use vLLM engine default continuous batching.
    [int] $MaxNumSeqs = 0,
    [int] $MaxModelLen = 4096,
    [double] $GpuMemoryUtilization = 0.90,
    [switch] $EnforceEager,
    [switch] $SkipPublish,
    [int] $TimeoutSec = 7200
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
Ensure-AwsCli
$Region = Get-AwsRegion -Region $Region
Ensure-ClusterInstances -Region $Region -RequireGpu -RequireDb:$false -RequireNl2sql:$false
$bird = Get-BirdDatasetConfig -Bucket $Bucket -Version $Version
$targets = Resolve-ClusterTargets -GpuInstanceId $GpuInstanceId -Region $Region -RequireGpu -RequireDb:$false -RequireNl2sql:$false

if (-not $SkipPublish) {
    & (Join-Path $PSScriptRoot "publish-package-to-s3.ps1") -Version $bird.Version -Bucket $bird.Bucket -Region $Region
}

Write-Host "Deploying GPU vLLM on $($targets.GpuInstanceId) model=$Model max-model-len=$MaxModelLen gpu-mem-util=$GpuMemoryUtilization"

$envMap = @{
    BIRD_DATASET_BUCKET          = $bird.Bucket
    BIRD_DATASET_VERSION         = $bird.Version
    VLLM_MODEL                   = $Model
    VLLM_MAX_MODEL_LEN           = "$MaxModelLen"
    VLLM_GPU_MEMORY_UTILIZATION  = ("{0:F2}" -f $GpuMemoryUtilization)
    AWS_DEFAULT_REGION           = $Region
}
if ($MaxNumSeqs -gt 0) {
    $envMap["VLLM_MAX_NUM_SEQS"] = "$MaxNumSeqs"
    Write-Host "Ops override: VLLM_MAX_NUM_SEQS=$MaxNumSeqs"
}
if ($EnforceEager) {
    $envMap["VLLM_ENFORCE_EAGER"] = "1"
}

& (Join-Path $PSScriptRoot "invoke-ssm.ps1") `
    -InstanceId $targets.GpuInstanceId `
    -ScriptPath (Join-Path $PSScriptRoot "ssm-deploy-gpu-vllm.sh") `
    -Region $Region `
    -Env $envMap `
    -TimeoutSec $TimeoutSec

$vllmBase = if ($targets.GpuPrivateIp) { "http://$($targets.GpuPrivateIp):11434" } else { $null }
Write-Host "GPU vLLM deploy complete. VLLM_BASE_URL=$vllmBase (OpenAI /v1)"

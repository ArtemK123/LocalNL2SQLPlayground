<#
.SYNOPSIS
  Publish package to S3 (optional) and deploy Ollama on the GPU EC2 host via SSM.
#>
param(
    [string] $GpuInstanceId,
    [string] $Bucket,
    [string] $Version,
    [string] $Region,
    [string] $ActiveModel = "arctic-text2sql-r1-7b:q4_k_m",
    [switch] $SkipPublish,
    [int] $TimeoutSec = 5400
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

Write-Host "Deploying GPU Ollama on $($targets.GpuInstanceId) (active model: $ActiveModel)"

& (Join-Path $PSScriptRoot "invoke-ssm.ps1") `
    -InstanceId $targets.GpuInstanceId `
    -ScriptPath (Join-Path $PSScriptRoot "ssm-deploy-gpu.sh") `
    -Region $Region `
    -Env @{
        BIRD_DATASET_BUCKET  = $bird.Bucket
        BIRD_DATASET_VERSION  = $bird.Version
        OLLAMA_ACTIVE_MODEL  = $ActiveModel
        AWS_DEFAULT_REGION   = $Region
    } `
    -TimeoutSec $TimeoutSec

Write-Host "GPU deploy complete. OLLAMA_HOST=$($targets.OllamaHost) active=$ActiveModel"

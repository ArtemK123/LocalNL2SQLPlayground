<#
.SYNOPSIS
  Upload BIRD to S3 (optional) and deploy/load DB on the DB EC2 host via SSM.

.DESCRIPTION
  - BIRD_dev.sql: laptop -> S3 only (upload-bird-to-s3.ps1)
  - DB EC2: downloads BIRD from S3 (stage-bird-assets.sh inside ssm-deploy-db-only.sh)
  - Application package: S3 package.tgz (not laptop scp)
#>
param(
    [string] $DbInstanceId,
    [string] $Bucket,
    [string] $Version,
    [string] $SqlPath,
    [switch] $SkipUpload,
    [int] $TimeoutSec = 3600
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
Ensure-AwsCli
$Region = Get-AwsRegion
Ensure-ClusterInstances -Region $Region -RequireDb -RequireGpu:$false -RequireNl2sql:$false

if (-not $Version) { $Version = (Get-BirdDatasetConfig).Version }
if (-not $Bucket) { $Bucket = (Get-BirdDatasetConfig -Version $Version).Bucket }

if (-not $SkipUpload) {
    $uploadArgs = @{
        Bucket  = $Bucket
        Version = $Version
        ReadBucketFromTfvars = $true
    }
    if ($SqlPath) { $uploadArgs["SqlPath"] = $SqlPath }
    & (Join-Path $PSScriptRoot "upload-bird-to-s3.ps1") @uploadArgs
    if (-not $Bucket) {
        $Bucket = Get-Tfvar -Name "bird_dataset_bucket"
    }
}

# Ensure operator package is on S3 (small; not the BIRD dump)
& (Join-Path $PSScriptRoot "publish-package-to-s3.ps1") -Version $Version -Bucket $Bucket

if (-not $DbInstanceId) {
    $targets = Resolve-ClusterTargets -Region $Region -RequireDb -RefreshCredentials
    $DbInstanceId = $targets.DbInstanceId
}

Write-Host "Deploying DB on $DbInstanceId (BIRD from s3://$Bucket/nl2sql-comparison/bird/$Version/)"

& (Join-Path $PSScriptRoot "invoke-ssm.ps1") `
    -InstanceId $DbInstanceId `
    -ScriptPath (Join-Path $PSScriptRoot "ssm-deploy-db-only.sh") `
    -Region $Region `
    -Env @{
        BIRD_DATASET_BUCKET  = $Bucket
        BIRD_DATASET_VERSION = $Version
        PACKAGE_VERSION      = $Version
        AWS_DEFAULT_REGION   = $Region
    } `
    -TimeoutSec $TimeoutSec

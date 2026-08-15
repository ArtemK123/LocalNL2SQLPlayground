param([switch] $SkipUpload, [switch] $SkipPublish)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
Ensure-AwsCli
Ensure-ClusterInstances
$targets = Resolve-ClusterTargets
$cfg = Get-PackageDatasetConfig
if (-not $SkipUpload) { & "$PSScriptRoot\upload-bird-to-s3.ps1" -Bucket $cfg.Bucket -Version $cfg.Version }
if (-not $SkipPublish) { & "$PSScriptRoot\publish-package-to-s3.ps1" -Bucket $cfg.Bucket -Version $cfg.Version }
& "$PSScriptRoot\invoke-ssm.ps1" -InstanceId $targets.DbInstanceId -ScriptPath "scripts/aws/ssm-deploy-db-only.sh" -Env @{
    BIRD_DATASET_BUCKET  = $cfg.Bucket
    BIRD_DATASET_PREFIX  = $cfg.Prefix
    BIRD_DATASET_VERSION = $cfg.Version
    PACKAGE_VERSION      = $cfg.Version
    AWS_DEFAULT_REGION   = $targets.Region
}

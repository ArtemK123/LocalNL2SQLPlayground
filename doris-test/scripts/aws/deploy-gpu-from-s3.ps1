param([switch] $SkipPublish)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
$targets = Resolve-ClusterTargets
$cfg = Get-PackageDatasetConfig
if (-not $SkipPublish) { & "$PSScriptRoot\publish-package-to-s3.ps1" -Bucket $cfg.Bucket -Version $cfg.Version }
& "$PSScriptRoot\invoke-ssm.ps1" -InstanceId $targets.GpuInstanceId -ScriptPath "scripts/aws/ssm-deploy-gpu.sh" -Env @{
    PACKAGE_BUCKET = $cfg.Bucket; PACKAGE_PREFIX = $cfg.Prefix; PACKAGE_VERSION = $cfg.Version
}

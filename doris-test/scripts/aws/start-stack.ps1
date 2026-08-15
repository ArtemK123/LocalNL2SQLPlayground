param([switch] $WithUI)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
$targets = Resolve-ClusterTargets
$profile = if ($WithUI) { "--profile ui" } else { "" }
& "$PSScriptRoot\invoke-ssm.ps1" -InstanceId $targets.Nl2sqlInstanceId -ScriptPath "scripts/aws/ssm-deploy-nl2sql.sh" -Env @{
    PACKAGE_BUCKET = (Get-PackageDatasetConfig).Bucket
    PACKAGE_PREFIX = (Get-PackageDatasetConfig).Prefix
    PACKAGE_VERSION = (Get-PackageDatasetConfig).Version
    OLLAMA_HOST = $targets.OllamaHost
    DORIS_FE_HOST = $targets.DorisFeHost
}

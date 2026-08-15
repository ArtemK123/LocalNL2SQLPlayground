$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
Ensure-AwsCli
$targets = Resolve-ClusterTargets
& "$PSScriptRoot\invoke-ssm.ps1" -InstanceId $targets.DbInstanceId -ScriptPath "scripts/aws/smoke-replication-parity.sh" -Env @{
    BIRD_PG_HOST = "127.0.0.1"; DORIS_FE_HOST = $targets.AnalyticsPrivateIp
} -AllowNonZeroExit 2>$null
& "$PSScriptRoot\invoke-ssm.ps1" -InstanceId $targets.Nl2sqlInstanceId -ScriptPath "scripts/aws/ssm-smoke-langchain.sh"
Write-Host "Cluster smoke finished."

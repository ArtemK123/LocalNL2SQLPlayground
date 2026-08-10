<#
.SYNOPSIS
  Deploy one NL2SQL framework on AWS via SSM (remote DB + remote GPU Ollama).

.NOTES
  Manual GPU model switch required before some stacks:
  - SQL stacks (langchain, premsql, vanna, wrenai): set-gpu-model.ps1 -ModelProfile sql
  - dbgpt, chat2db: set-gpu-model.ps1 -ModelProfile general
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("langchain", "dbgpt", "premsql", "vanna", "wrenai", "chat2db")]
    [string] $Stack,

    [switch] $SkipGpuCheck,
    [switch] $SkipPublish,
    [switch] $WrenResyncModel,
    [string] $Region,
    [int] $TimeoutSec = 7200
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_experiment-common.ps1"
Ensure-AwsCli
$Region = Get-AwsRegion -Region $Region
Ensure-ClusterInstances -Region $Region -RequireDb -RequireGpu -RequireNl2sql
$targets = Resolve-ClusterTargets -Region $Region

Write-Host "Cluster: DB=$($targets.DbPrivateIp) GPU=$($targets.GpuPrivateIp) NL2SQL=$($targets.Nl2sqlInstanceId)"

if (-not $SkipGpuCheck) {
    Write-Host "Ensuring GPU Ollama is up (deploy-gpu-from-s3.ps1)..."
    & (Join-Path $PSScriptRoot "deploy-gpu-from-s3.ps1") -Region $Region -SkipPublish:$SkipPublish
}

& (Join-Path $PSScriptRoot "smoke-aws-stack.ps1") `
    -Stack $Stack `
    -Region $Region `
    -SkipPublish:$SkipPublish `
    -WrenResyncModel:$WrenResyncModel `
    -TimeoutSec $TimeoutSec

$ports = @{ langchain = "8011,8501"; dbgpt = "8012,5670"; premsql = "8501,8000,8010"; vanna = "8001"; wrenai = "3001"; chat2db = "10825" }
$p = $ports[$Stack]
Write-Host "start-stack $Stack : OK on NL2SQL host."
Write-Host "Open UI on laptop: .\scripts\aws\port-forward-ui.ps1 -Stack $Stack"
Write-Host "  (forwards port $p to http://127.0.0.1:<port>/)"

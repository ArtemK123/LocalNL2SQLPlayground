<#
.SYNOPSIS
  Deploy one NL2SQL framework on the NL2SQL EC2 host and run its health smoke via SSM.

.DESCRIPTION
  Uses remote GPU Ollama (OLLAMA_HOST) and remote DB (BIRD_PG_HOST). Does not start Ollama on the NL2SQL host.
  WrenAI: skips semantic model re-index unless -WrenResyncModel (slow; re-embeds all tables).
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("langchain", "dbgpt", "premsql", "vanna", "wrenai", "chat2db")]
    [string] $Stack,

    [switch] $SkipGpuModelSwitch,
    [string] $Nl2sqlInstanceId,
    [string] $DbPrivateIp,
    [string] $OllamaHost,
    [string] $Bucket,
    [string] $Version,
    [string] $Region,
    [switch] $SkipPublish,
    [string] $WrenTargetTables,
    [string] $WrenTargetSchemas,
    [switch] $WrenResyncModel,
    [string] $OllamaPrimaryModel,
    [string] $OllamaFallbackModel,
    [ValidateSet("ollama", "vllm")]
    [string] $LlmBackend = "ollama",
    [int] $TimeoutSec = 7200
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_experiment-common.ps1"
Ensure-AwsCli
$Region = Get-AwsRegion -Region $Region
Ensure-ClusterInstances -Region $Region -RequireDb -RequireGpu -RequireNl2sql
$bird = Get-BirdDatasetConfig -Bucket $Bucket -Version $Version
$targets = Resolve-ClusterTargets -Nl2sqlInstanceId $Nl2sqlInstanceId -Region $Region -RequireDb -RequireGpu -RequireNl2sql

if (-not $DbPrivateIp) { $DbPrivateIp = $targets.DbPrivateIp }
if (-not $OllamaHost) {
    if ($targets.OllamaHost) { $OllamaHost = $targets.OllamaHost }
    else { throw "OLLAMA_HOST not set and GPU instance is not running. Pass -OllamaHost or run deploy-gpu-from-s3.ps1 after terraform apply." }
}

if (-not $SkipPublish) {
    & (Join-Path $PSScriptRoot "publish-package-to-s3.ps1") -Version $bird.Version -Bucket $bird.Bucket -Region $Region
}

if ($LlmBackend -eq "ollama") {
    if ($Stack -in $script:SqlStacks) {
        Assert-GpuSqlInfrastructure -Region $Region -GpuInstanceId $targets.GpuInstanceId
    }
    Ensure-GpuModelForStack -Stack $Stack -Region $Region -GpuInstanceId $targets.GpuInstanceId -SkipGpuModelSwitch:$SkipGpuModelSwitch
} else {
    Write-Host "LLM_BACKEND=vllm - skipping Ollama model switch / Assert-GpuSqlInfrastructure"
    $SkipGpuModelSwitch = $true
}

Write-Host "SSM smoke: stack=$Stack instance=$($targets.Nl2sqlInstanceId) db=$DbPrivateIp llm=$LlmBackend endpoint=$OllamaHost"

$ssmEnv = @{
    NL2SQL_STACK         = $Stack
    BIRD_PG_HOST         = $DbPrivateIp
    OLLAMA_HOST          = $OllamaHost
    VLLM_BASE_URL        = $OllamaHost
    LLM_BACKEND          = $LlmBackend
    BIRD_DATASET_BUCKET  = $bird.Bucket
    BIRD_DATASET_VERSION = $bird.Version
    AWS_DEFAULT_REGION   = $Region
    USE_LOCAL_OLLAMA     = "false"
}
if ($Stack -eq "langchain") {
    $ssmEnv["OLLAMA_NUM_PREDICT"] = "512"
    $ssmEnv["ARCTIC_SQL_FENCE_PREFILL"] = "true"
    $ssmEnv["LLM_HTTP_TIMEOUT_SEC"] = "20"
}
if ($LlmBackend -eq "vllm") {
    $ssmEnv["OLLAMA_PRIMARY_MODEL"] = $(if ($OllamaPrimaryModel) { $OllamaPrimaryModel } else { "Snowflake/Arctic-Text2SQL-R1-7B" })
    $ssmEnv["OLLAMA_FALLBACK_MODEL"] = $ssmEnv["OLLAMA_PRIMARY_MODEL"]
}
if ($WrenTargetTables) { $ssmEnv["WREN_TARGET_TABLES"] = $WrenTargetTables }
if ($WrenTargetSchemas) { $ssmEnv["WREN_TARGET_SCHEMAS"] = $WrenTargetSchemas }
if ($WrenResyncModel) { $ssmEnv["WREN_RESYNC_MODEL"] = "true" }
if ($OllamaPrimaryModel) { $ssmEnv["OLLAMA_PRIMARY_MODEL"] = $OllamaPrimaryModel }
if ($OllamaFallbackModel) { $ssmEnv["OLLAMA_FALLBACK_MODEL"] = $OllamaFallbackModel }

& (Join-Path $PSScriptRoot "invoke-ssm.ps1") `
    -InstanceId $targets.Nl2sqlInstanceId `
    -ScriptPath (Join-Path $PSScriptRoot "ssm-smoke-stack.sh") `
    -Region $Region `
    -Env $ssmEnv `
    -TimeoutSec $TimeoutSec

Write-Host "smoke-aws-stack $Stack : OK"

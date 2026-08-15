param([switch] $SkipPublish, [string] $LlmBackend = "ollama", [string] $ArcticSqlDialect = "mysql", [string] $DbBackend = "doris")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
$targets = Resolve-ClusterTargets
$cfg = Get-PackageDatasetConfig
if (-not $SkipPublish) { & "$PSScriptRoot\publish-package-to-s3.ps1" -Bucket $cfg.Bucket -Version $cfg.Version }
$envMap = @{
    PACKAGE_BUCKET       = $cfg.Bucket
    PACKAGE_PREFIX       = $cfg.Prefix
    PACKAGE_VERSION      = $cfg.Version
    OLLAMA_HOST          = $targets.OllamaHost
    VLLM_BASE_URL        = $targets.OllamaHost
    LLM_BACKEND          = $LlmBackend
    DORIS_FE_HOST        = $targets.DorisFeHost
    ARCTIC_SQL_DIALECT   = $ArcticSqlDialect
    DB_BACKEND           = $DbBackend
    SQL_EXEC_MODE        = "skip"
    SCHEMA_SOURCE        = "bird_tables"
    SCHEMA_SELECTOR_MODE = "bm25"
}
if ($DbBackend -eq "postgres") {
    $envMap["BIRD_PG_HOST"] = $targets.DbPrivateIp
}
if ($LlmBackend -eq "vllm") {
    $envMap["OLLAMA_PRIMARY_MODEL"] = "Snowflake/Arctic-Text2SQL-R1-7B"
    $envMap["OLLAMA_FALLBACK_MODEL"] = "Snowflake/Arctic-Text2SQL-R1-7B"
}
& "$PSScriptRoot\invoke-ssm.ps1" -InstanceId $targets.Nl2sqlInstanceId -ScriptPath "scripts/aws/ssm-deploy-nl2sql.sh" -Env $envMap

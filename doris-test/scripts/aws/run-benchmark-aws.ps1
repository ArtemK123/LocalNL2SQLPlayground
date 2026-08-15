<#
.SYNOPSIS
  Run Arctic+vLLM (or Ollama) harness experiments against doris-test with selectable eval backend.
#>
param(
    [string] $Profile = "experiments/profiles/arctic-vllm-studyparity-doris-diverse10.json",
    [string] $Suite,
    [string] $EvalMode,
    [string] $Model,
    [string] $RunId,
    [string] $JudgeBaseUrl,
    [string] $JudgeModel,
    [switch] $SkipPublish,
    [switch] $SkipDeploy,
    [switch] $SkipPreflight,
    [switch] $SkipHealthGate,
    [switch] $KeepTunnels,
    [switch] $DryRun,
    [string] $Region
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"

$root = Get-DorisTestRoot
Set-Location $root

$profilePath = if ([IO.Path]::IsPathRooted($Profile)) { $Profile } else { Join-Path $root $Profile }
if (-not (Test-Path $profilePath)) { throw "Profile not found: $profilePath" }
$profileData = Get-Content $profilePath -Raw | ConvertFrom-Json

$suite = if ($Suite) { $Suite } elseif ($profileData.suite) { [string]$profileData.suite } else { "smoke_3" }
$evalMode = if ($EvalMode) { $EvalMode } elseif ($profileData.eval_mode) { [string]$profileData.eval_mode } else { "dual_dsn" }
$model = if ($Model) { $Model } elseif ($profileData.model) { [string]$profileData.model } else { "Snowflake/Arctic-Text2SQL-R1-7B" }
$workers = if ($null -ne $profileData.workers) { [int]$profileData.workers } else { 1 }
$timeoutSec = if ($null -ne $profileData.timeout_sec) { [double]$profileData.timeout_sec } else { 120 }
$llmBackend = if ($profileData.llm_backend) { [string]$profileData.llm_backend } else { "ollama" }
$arcticDialect = if ($profileData.arctic_sql_dialect) { [string]$profileData.arctic_sql_dialect } else { "mysql" }
$dbBackend = if ($profileData.db_backend) { [string]$profileData.db_backend } else { "doris" }
$sqlExecMode = if ($profileData.sql_exec_mode) { [string]$profileData.sql_exec_mode } else { "skip" }
$goldDsn = if ($profileData.gold_dsn) { [string]$profileData.gold_dsn } else { "postgresql://olap:olap@127.0.0.1:55433/bird" }
$predDsn = if ($profileData.pred_dsn) { [string]$profileData.pred_dsn } else { "mysql://root@127.0.0.1:9031/bird_minidev_olap" }
$apiUrl = if ($profileData.api_url) { [string]$profileData.api_url } else { "http://127.0.0.1:8011/v1/chat" }
$sqliteDir = if ($profileData.sqlite_databases_dir) { [string]$profileData.sqlite_databases_dir } else { $null }
$exMode = if ($profileData.ex_mode) { [string]$profileData.ex_mode } else { "bird" }
$judgeBaseUrl = if ($JudgeBaseUrl) { $JudgeBaseUrl } elseif ($profileData.judge_base_url) { [string]$profileData.judge_base_url } else { $env:JUDGE_BASE_URL }
if (-not $judgeBaseUrl) { $judgeBaseUrl = $env:VLLM_BASE_URL }
$judgeModel = if ($JudgeModel) { $JudgeModel } elseif ($profileData.judge_model) { [string]$profileData.judge_model } else { $env:JUDGE_MODEL }
if (-not $judgeModel) { $judgeModel = "Snowflake/Arctic-Text2SQL-R1-7B" }
$skipPublish = $SkipPublish -or ($profileData.skip_publish -eq $true)
$skipDeploy = $SkipDeploy -or ($profileData.skip_deploy -eq $true)

if (-not $RunId) { $RunId = "doris_" + (Get-Date -Format "yyyyMMdd_HHmmss") }
$resultsDir = Join-Path $root "results\$RunId"
$jsonlDir = Join-Path $resultsDir "jsonl"
New-Item -ItemType Directory -Force -Path $jsonlDir | Out-Null

Write-Host @"

=== doris-test AWS experiment ===
  run_id:     $RunId
  suite:      $suite
  eval_mode:  $evalMode
  llm:        $llmBackend
  dialect:    $arcticDialect
  db_backend: $dbBackend
  model:      $model
  workers:    $workers
  timeout:    $timeoutSec

"@

if ($DryRun) {
    Write-Host "DryRun - exiting before deploy/harness."
    exit 0
}

if (-not $SkipPreflight) {
    Ensure-AwsCli
    & "$PSScriptRoot\ensure-cluster.ps1" -Region $Region
}

$targets = Resolve-ClusterTargets -Region $Region

if (-not $skipDeploy) {
    if (-not $skipPublish) {
        $cfg = Get-PackageDatasetConfig
        & "$PSScriptRoot\publish-package-to-s3.ps1" -Bucket $cfg.Bucket -Version $cfg.Version
    }
    $cfg = Get-PackageDatasetConfig
    $envMap = @{
        PACKAGE_BUCKET       = $cfg.Bucket
        PACKAGE_PREFIX       = $cfg.Prefix
        PACKAGE_VERSION      = $cfg.Version
        OLLAMA_HOST          = $targets.OllamaHost
        VLLM_BASE_URL        = $targets.OllamaHost
        LLM_BACKEND          = $llmBackend
        DORIS_FE_HOST        = $targets.DorisFeHost
        OLLAMA_PRIMARY_MODEL = $model
        ARCTIC_SQL_DIALECT   = $arcticDialect
        DB_BACKEND           = $dbBackend
        SQL_EXEC_MODE        = $sqlExecMode
        SCHEMA_SOURCE        = "bird_tables"
        SCHEMA_SELECTOR_MODE = "bm25"
        OLLAMA_NUM_PREDICT   = "512"
        LLM_HTTP_TIMEOUT_SEC = "20"
    }
    if ($dbBackend -eq "postgres") {
        $envMap["BIRD_PG_HOST"] = $targets.DbPrivateIp
    }
    & "$PSScriptRoot\invoke-ssm.ps1" -InstanceId $targets.Nl2sqlInstanceId `
        -ScriptPath (Join-Path $PSScriptRoot "ssm-deploy-nl2sql.sh") -Env $envMap
}

# SSH tunnels: laptop is the preferred scoring host (reaches gold PG + Doris).
# Do NOT score gold from nl2sql under default SG (db:5432 blocked) — see EXPERIMENTS.md.
Write-Host "Ensure tunnels: PG->55433, Doris->9031, API->8011 (see AI_OPERATIONS.md / write-ssh-config.ps1)"
& "$PSScriptRoot\write-ssh-config.ps1" -Region $Region

if (-not $SkipHealthGate -and $evalMode -in @("dual_dsn", "doris", "mysql", "dual_dsn_llm_judge", "judge_equiv")) {
    Write-Host "Running preflight-eval-health (Doris + gold PG via tunnels)..."
    & "$PSScriptRoot\preflight-eval-health.ps1" -PredDsn $predDsn -GoldDsn $goldDsn
}

$outJsonl = Join-Path $jsonlDir "langchain_$suite.jsonl"
$harnessArgs = @(
    "run-api",
    "--suite", $suite,
    "--api-url", $apiUrl,
    "--eval-mode", $evalMode,
    "--timeout", "$timeoutSec",
    "--workers", "$workers",
    "--out", $outJsonl,
    "--ex-mode", $exMode
)
if ($evalMode -in @("dual_dsn", "doris", "mysql", "dual_dsn_llm_judge", "judge_equiv")) {
    $harnessArgs += @("--gold-dsn", $goldDsn, "--pred-dsn", $predDsn)
} elseif ($evalMode -eq "postgres") {
    $harnessArgs += @("--gold-dsn", $goldDsn)
} elseif ($evalMode -eq "sqlite") {
    if (-not $sqliteDir) { throw "eval_mode=sqlite requires profile sqlite_databases_dir" }
    $harnessArgs += @("--sqlite-databases-dir", $sqliteDir)
}
if ($evalMode -in @("dual_dsn_llm_judge", "judge_equiv")) {
    if (-not $judgeBaseUrl) {
        throw "eval_mode=$evalMode requires -JudgeBaseUrl / profile judge_base_url / JUDGE_BASE_URL / VLLM_BASE_URL"
    }
    $harnessArgs += @("--judge-base-url", $judgeBaseUrl, "--judge-model", $judgeModel)
}

Push-Location (Join-Path $root "harness")
try {
    py -3.13 -m pip install -e . -q
    & py -3.13 -m doris_test_harness @harnessArgs
    if ($LASTEXITCODE -ne 0) { throw "harness failed ($LASTEXITCODE)" }
}
finally {
    Pop-Location
}

$manifest = [ordered]@{
    run_id             = $RunId
    suite              = $suite
    model              = $model
    llm_backend        = $llmBackend
    eval_mode          = $evalMode
    arctic_sql_dialect = $arcticDialect
    db_backend         = $dbBackend
    sql_exec_mode      = $sqlExecMode
    ex_mode            = $exMode
    workers            = $workers
    timeout_sec        = $timeoutSec
    gold_dsn           = ($goldDsn -replace "://[^@]+@", "://***@")
    pred_dsn           = ($predDsn -replace "://[^@]+@", "://***@")
    api_url            = $apiUrl
    judge_base_url     = $judgeBaseUrl
    judge_model        = $judgeModel
    scoring_host       = "laptop_tunnels"
    jsonl              = $outJsonl
    started_note       = "Arctic Doris dual-DSN path; score on laptop tunnels (not nl2sql SG)"
    cluster            = @{
        region       = $targets.Region
        db_ip        = $targets.DbPrivateIp
        gpu_ip       = $targets.GpuPrivateIp
        analytics_ip = $targets.AnalyticsPrivateIp
        ollama       = $targets.OllamaHost
    }
}
$manifestPath = Join-Path $resultsDir "manifest.json"
($manifest | ConvertTo-Json -Depth 6) | Set-Content -Path $manifestPath -Encoding utf8
Write-Host "Wrote $manifestPath"
if (-not $KeepTunnels) {
    Write-Host "Tunnels left running; stop manually if needed."
}

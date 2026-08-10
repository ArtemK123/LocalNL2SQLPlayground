<#
.SYNOPSIS
  Run NL2SQL harness benchmarks on AWS (laptop Playwright + SSH tunnels + remote stacks).

.DESCRIPTION
  Orchestrates: cluster preflight, optional package publish, per-stack SSM deploy,
  SSH port-forwards, harness runs (headless by default), and results/<run_id>/ manifest + summary.

  Stacks run one at a time on the NL2SQL host. Use -Profile for repeatable experiment configs.

.EXAMPLE
  .\scripts\aws\run-benchmark-aws.ps1 -ProbeOnly

.EXAMPLE
  .\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/arctic-small10-all.json -SkipPublish

.EXAMPLE
  .\scripts\aws\run-benchmark-aws.ps1 -Stacks langchain,dbgpt -Suite smoke_3 -ExcludeStacks chat2db

.EXAMPLE
  .\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/arctic-vllm-studyparity-postgres-full.json -SkipPublish
#>
param(
    [string] $Profile,
    [string[]] $Stacks,
    [string[]] $ExcludeStacks,
    [ValidateSet("smoke_3", "small_10", "medium_25", "big_100", "full", "minidev_diverse_10", "formula_1_smoke_10")]
    [string] $Suite,
    [ValidateSet("api", "ui")]
    [string] $Mode,
    [int] $Workers,
    [switch] $AdaptiveSuite,
    [switch] $ProbeOnly,
    [string] $RunId,
    [string] $Model,
    [string] $FallbackModel,
    [switch] $Headed,
    [switch] $NoHeaded,
    [double] $Timeout = 900,
    [switch] $SkipPublish,
    [switch] $SkipDeploy,
    [switch] $WrenResyncModel,
    [switch] $SkipModelCheck,
    [switch] $SkipPreflight,
    [switch] $SkipTunnels,
    [switch] $KeepTunnels,
    [switch] $DryRun,
    [string] $Region,
    [string] $SshConfigPath,
    [string] $KeyPath,
    [ValidateSet("auto", "ssm", "ssh")]
    [string] $TunnelMode = "auto"
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_experiment-common.ps1"

$profileData = Import-ExperimentProfile -ProfilePath $Profile
function Resolve-Param {
    param($Cli, $ProfileKey, $Default = $null)
    if ($null -ne $Cli -and $Cli -ne "") { return $Cli }
    if ($profileData.ContainsKey($ProfileKey) -and $null -ne $profileData[$ProfileKey]) { return $profileData[$ProfileKey] }
    return $Default
}

$stacksResolved = Resolve-ExperimentStacks `
    -Stacks $Stacks `
    -ExcludeStacks $ExcludeStacks `
    -ProfileStacks $(if ($profileData.stacks) { @($profileData.stacks) } else { $null })

$suite = Resolve-Param -Cli $Suite -ProfileKey "suite" -Default "small_10"
$runId = Resolve-Param -Cli $RunId -ProfileKey "run_id" -Default (New-ExperimentRunId)
$model = Resolve-Param -Cli $Model -ProfileKey "model" -Default "a-kore/Arctic-Text2SQL-R1-7B"
$fallback = Resolve-Param -Cli $FallbackModel -ProfileKey "fallback_model" -Default $model
if ($PSBoundParameters.ContainsKey("Timeout")) {
    $timeoutSec = [double]$Timeout
} elseif ($profileData.ContainsKey("timeout_sec") -and $null -ne $profileData["timeout_sec"]) {
    $timeoutSec = [double]$profileData["timeout_sec"]
} else {
    $timeoutSec = 900
}
if ($PSBoundParameters.ContainsKey("Mode") -and $Mode) {
    $mode = $Mode
} elseif ($profileData.ContainsKey("mode") -and $profileData["mode"]) {
    $mode = [string]$profileData["mode"]
} else {
    $mode = "ui"
}
if ($mode -notin @("api", "ui")) {
    throw "Invalid mode '$mode' (expected api|ui)."
}
if ($PSBoundParameters.ContainsKey("Workers")) {
    $workers = [int]$Workers
} elseif ($profileData.ContainsKey("workers") -and $null -ne $profileData["workers"]) {
    $workers = [int]$profileData["workers"]
} else {
    $workers = 1
}
if ($workers -lt 1) { throw "-Workers / profile workers must be >= 1 (got $workers)." }
$adaptive = $AdaptiveSuite -or ($profileData.adaptive_suite -eq $true)

$evalEngine = "postgres"
if ($profileData.ContainsKey("eval_engine") -and $profileData["eval_engine"]) {
    $evalEngine = [string]$profileData["eval_engine"]
}
$exMode = "multiset"
if ($profileData.ContainsKey("ex_mode") -and $profileData["ex_mode"]) {
    $exMode = [string]$profileData["ex_mode"]
}
# Prompt dialect for Arctic OmniSQL "Database Engine:" line. Default follows eval_engine.
$arcticSqlDialect = $null
if ($profileData.ContainsKey("arctic_sql_dialect") -and $profileData["arctic_sql_dialect"]) {
    $arcticSqlDialect = [string]$profileData["arctic_sql_dialect"]
} elseif ($evalEngine -eq "sqlite") {
    $arcticSqlDialect = "sqlite"
} else {
    $arcticSqlDialect = "postgresql"
}
$arcticSqlDialect = $arcticSqlDialect.Trim().ToLowerInvariant()
if ($arcticSqlDialect -in @("postgres", "pg", "postgresql")) {
    $arcticSqlDialect = "postgresql"
} else {
    $arcticSqlDialect = "sqlite"
}
$env:ARCTIC_SQL_DIALECT = $arcticSqlDialect
$sqliteDatabasesDir = $null
if ($profileData.ContainsKey("sqlite_databases_dir") -and $profileData["sqlite_databases_dir"]) {
    $sqliteDatabasesDir = [string]$profileData["sqlite_databases_dir"]
}
if ($evalEngine -eq "sqlite" -and -not $sqliteDatabasesDir) {
    $candidate = "C:\Datasets\bird\minidev\MINIDEV\dev_databases"
    if (Test-Path $candidate) { $sqliteDatabasesDir = $candidate }
}
if ($evalEngine -eq "sqlite" -and -not $sqliteDatabasesDir) {
    throw "eval_engine=sqlite requires profile sqlite_databases_dir (or C:\Datasets\bird\minidev\MINIDEV\dev_databases)"
}
$probeOnly = $ProbeOnly -or ($profileData.probe_only -eq $true)
$skipPublish = $SkipPublish -or ($profileData.skip_publish -eq $true)
$skipDeploy = $SkipDeploy -or ($profileData.skip_deploy -eq $true)
$skipModelCheck = $SkipModelCheck -or ($profileData.skip_model_check -eq $true)
$llmBackend = if ($profileData.ContainsKey("llm_backend") -and $profileData["llm_backend"]) {
    [string]$profileData["llm_backend"]
} elseif ($env:NL2SQL_LLM_BACKEND) {
    $env:NL2SQL_LLM_BACKEND
} else {
    "ollama"
}
$llmBackend = $llmBackend.Trim().ToLowerInvariant()
if ($llmBackend -notin @("ollama", "vllm")) {
    throw "Invalid llm_backend '$llmBackend' (expected ollama|vllm)."
}
if ($llmBackend -eq "vllm") {
    # vLLM serves HuggingFace ids; Ollama /api/tags model switch does not apply.
    $skipModelCheck = $true
    $env:NL2SQL_LLM_BACKEND = "vllm"
} else {
    $env:NL2SQL_LLM_BACKEND = "ollama"
}
$headed = $false
if ($profileData.headed -eq $true) { $headed = $true }
if ($Headed) { $headed = $true }
if ($NoHeaded) { $headed = $false }
if ($mode -eq "api") { $headed = $false }

$apiStacks = @("langchain", "dbgpt")
if ($mode -eq "api") {
    $unsupported = @($stacksResolved | Where-Object { $_ -notin $apiStacks })
    if ($unsupported.Count -gt 0) {
        throw "mode=api supports only $($apiStacks -join ', '); unsupported: $($unsupported -join ', ')"
    }
}

$Region = Get-AwsRegion -Region $Region
$resultsDir = Get-ExperimentResultsDir -RunId $runId
$jsonlDir = Join-Path $resultsDir "jsonl"

$stackModelsMap = Resolve-StackModelsMap -Stacks $stacksResolved -ProfileData $profileData -SqlDefault $model
$modelsDisplay = ($stackModelsMap.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ", "

Write-Host @"

=== NL2SQL AWS experiment ===
  run_id:    $runId
  suite:     $suite
  mode:      $mode
  workers:   $workers
  llm:       $llmBackend
  stacks:    $($stacksResolved -join ', ')
  sql_model: $model
  per_stack: $modelsDisplay
  timeout:   ${timeoutSec}s per question
  eval:      $evalEngine / ex_mode=$exMode
  dialect:   $arcticSqlDialect
  headed:    $headed
  skip_deploy: $skipDeploy
  results:   $resultsDir
"@ -ForegroundColor Cyan

if ($DryRun) {
    Write-Host "[DryRun] Would run preflight, tunnels, and $($stacksResolved.Count) stack(s)." -ForegroundColor Yellow
    exit 0
}

Ensure-AwsCli
if (-not $SkipPreflight) {
    & (Join-Path $PSScriptRoot "ensure-cluster.ps1") -Region $Region
}

$targets = Resolve-ClusterTargets -Region $Region
$pyVer = Ensure-HarnessInstalled

$tunnelState = $null
if (-not $SkipTunnels) {
    & (Join-Path $PSScriptRoot "write-ssh-config.ps1") -SshConfigPath $SshConfigPath -KeyPath $KeyPath -ErrorAction SilentlyContinue | Out-Null
    $tunnelState = Start-ExperimentTunnels -SshConfigPath $SshConfigPath -KeyPath $KeyPath -TunnelMode $TunnelMode -Region $Region
    Start-Sleep -Seconds 2
}

try {
    if ($llmBackend -eq "vllm") {
        $gpuActiveAtStart = "vllm:$model"
        Write-Host "GPU backend=vLLM model=$model (skip Ollama active-model probe)" -ForegroundColor Cyan
        if (-not $skipDeploy) {
            Write-Host "=== Deploy GPU vLLM (L4 capacity defaults; harness workers=$workers) ===" -ForegroundColor Cyan
            $deployArgs = @{
                Region       = $Region
                Model        = $model
                SkipPublish  = $skipPublish
                TimeoutSec   = 7200
            }
            # Optional ops-only override; prefer omitting so engine continuous batching defaults apply.
            if ($profileData.ContainsKey("vllm_max_num_seqs") -and $profileData["vllm_max_num_seqs"]) {
                $deployArgs["MaxNumSeqs"] = [int]$profileData["vllm_max_num_seqs"]
            }
            if ($profileData.ContainsKey("vllm_max_model_len") -and $profileData["vllm_max_model_len"]) {
                $deployArgs["MaxModelLen"] = [int]$profileData["vllm_max_model_len"]
            }
            & (Join-Path $PSScriptRoot "deploy-gpu-vllm-from-s3.ps1") @deployArgs
            $targets = Resolve-ClusterTargets -Region $Region
        }
    } else {
        $gpuActiveAtStart = Get-GpuActiveModel -Region $Region
        Write-Host "GPU active model at start: $gpuActiveAtStart" -ForegroundColor Cyan
    }

    if ($adaptive -or $probeOnly) {
        if ($skipDeploy) { throw "AdaptiveSuite/ProbeOnly require deploy; omit -SkipDeploy." }
        $probeModel = $stackModelsMap["langchain"]
        Assert-GpuActiveModel -ExpectedModel $probeModel -Stack "langchain" -Region $Region -SkipModelCheck:$skipModelCheck
        Write-Host "=== Probe: langchain + smoke_3 (mode=$mode) ===" -ForegroundColor Cyan
        Invoke-StackDeployAws -Stack "langchain" -Region $Region -SkipPublish:$skipPublish `
            -OllamaPrimaryModel $probeModel -OllamaFallbackModel $probeModel `
            -ArcticSqlDialect $arcticSqlDialect
        if ($mode -eq "api") {
            Write-Host "mode=api: skipping Chainlit UI (harness uses langchain API :8011)" -ForegroundColor Yellow
        } else {
            Start-LangchainChainlitUi -Region $Region
        }
        $probeOut = Join-Path $jsonlDir "probe_langchain_smoke_3.jsonl"
        Invoke-HarnessRun -Stack "langchain" -Suite "smoke_3" -PyVer $pyVer -OutPath $probeOut `
            -Timeout $timeoutSec -Mode $mode -Workers $workers -Headed:$headed -Trace:($mode -eq "ui") `
            -EvalEngine $evalEngine -SqliteDatabasesDir $sqliteDatabasesDir -ExMode $exMode
        $avgMs = Get-JsonlAverageLatencyMs -JsonlPath $probeOut
        $recommended = if ($avgMs -and $avgMs -gt 60000) { "small_10" } else { "medium_25" }
        Write-Host "Probe avg latency_ms=$([math]::Round($avgMs)) -> recommend suite: $recommended" -ForegroundColor Green
        if ($probeOnly) {
            $suite = "smoke_3"
        } elseif ($adaptive -and -not $Suite -and -not $profileData.suite) {
            $suite = $recommended
            Write-Host "Adaptive suite selected: $suite"
        }
    }

    if ($probeOnly) {
        Write-Host "ProbeOnly complete."
        exit 0
    }

    $jsonlPaths = @()
    $startedAt = (Get-Date).ToString("o")
    $frameworkRuns = @()

    foreach ($stack in $stacksResolved) {
        Write-Host "`n=== Stack: $stack ===" -ForegroundColor Cyan
        $stackModel = $stackModelsMap[$stack]
        Write-Host "Expected model: $stackModel"
        Assert-GpuActiveModel -ExpectedModel $stackModel -Stack $stack -Region $Region -SkipModelCheck:$skipModelCheck

        $wrenTables = $null
        $wrenSchemas = $null
        if ($stack -eq "wrenai") {
            $wrenTables = Get-WrenTargetTablesExport -Suite $suite -PyVer $pyVer -DbProfile "full"
            $wrenSchemas = Get-WrenMinidevSchemasCsv
            Write-Host "Wren deploy: WREN_TARGET_TABLES=$wrenTables schemas=minidev (11)"
        }

        if (-not $skipDeploy) {
            Invoke-StackDeployAws -Stack $stack -Region $Region -SkipPublish:$skipPublish `
                -WrenTargetTables $wrenTables -WrenTargetSchemas $wrenSchemas `
                -WrenResyncModel:$WrenResyncModel `
                -OllamaPrimaryModel $stackModel -OllamaFallbackModel $stackModel `
                -ArcticSqlDialect $arcticSqlDialect
        } else {
            Write-Host "SkipDeploy: leaving $stack containers as-is on NL2SQL host." -ForegroundColor Yellow
        }

        if ($stack -eq "langchain") {
            if ($mode -eq "api") {
                # API mode hits langchain_api on :8011; Chainlit (:8501) is unused.
                Write-Host "mode=api: skipping Chainlit UI start" -ForegroundColor Yellow
            } elseif (-not $skipDeploy) {
                Start-LangchainChainlitUi -Region $Region
                Start-Sleep -Seconds 5
            } else {
                Write-Host "SkipDeploy: assuming Chainlit already on :8501" -ForegroundColor Yellow
            }
        }
        if ($stack -eq "wrenai") { Start-Sleep -Seconds 20 }
        if ($stack -eq "chat2db") {
            Write-Host "=== Chat2DB Custom AI seed$(if ($headed) { ' (headed)' }) ===" -ForegroundColor Cyan
            $seed = Join-Path (Get-ExperimentRoot) "harness\scripts\seed_chat2db_ai_playwright.py"
            $seedArgs = @(
                $seed,
                "--ollama-url", $targets.OllamaHost,
                "--model", $stackModel
            )
            if ($headed) { $seedArgs += "--headed" }
            & py $pyVer @seedArgs
            if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
                Write-Warning "Chat2DB seed exited $LASTEXITCODE - continue if Custom AI was already configured."
            }
        }

        $outFile = Join-Path $jsonlDir "${stack}_${suite}.jsonl"
        Invoke-HarnessRun -Stack $stack -Suite $suite -PyVer $pyVer -OutPath $outFile `
            -Timeout $timeoutSec -Mode $mode -Workers $workers -Headed:$headed -Trace:($mode -eq "ui") `
            -EvalEngine $evalEngine -SqliteDatabasesDir $sqliteDatabasesDir -ExMode $exMode
        $jsonlPaths += $outFile
        $frameworkRuns += @{
            name  = $stack
            model = $stackModel
            suite = $suite
            mode  = $mode
        }

        if ($mode -eq "ui") {
            $traceSrc = Join-Path (Get-ExperimentRoot) "harness\runs\traces\${stack}_${suite}"
            if (Test-Path $traceSrc) {
                $traceDst = Join-Path $resultsDir "traces\${stack}_${suite}"
                Copy-Item -Path $traceSrc -Destination $traceDst -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }

    $tfGpu = Get-Tfvar -Name "gpu_instance_type"
    if (-not $tfGpu) { $tfGpu = "g6.xlarge" }

    $manifestNotes = if ($mode -eq "api") {
        "API mode (run-api) on laptop; workers=$workers; llm_backend=$llmBackend; eval_engine=$evalEngine ex_mode=$exMode arctic_sql_dialect=$arcticSqlDialect; stacks on NL2SQL EC2. Chainlit skipped for langchain."
    } else {
        "Playwright on laptop; stacks on NL2SQL EC2; llm_backend=$llmBackend; EX via forwarded DB port $($script:LocalDbForwardPort). Manual GPU model switch required when changing stack model profile."
    }
    Write-ExperimentManifest -ResultsDir $resultsDir -Fields @{
        run_id                   = $runId
        model                    = $model
        fallback_model           = $fallback
        models                   = $stackModelsMap
        llm_backend              = $llmBackend
        eval_engine              = $evalEngine
        ex_mode                  = $exMode
        arctic_sql_dialect       = $arcticSqlDialect
        sqlite_databases_dir     = $sqliteDatabasesDir
        gpu_active_model_at_start = $gpuActiveAtStart
        gpu_instance_type        = $tfGpu
        suite                    = $suite
        mode                     = $mode
        workers                  = $workers
        timeout_sec              = $timeoutSec
        questions_per_stack      = switch ($suite) {
            "smoke_3" { 3 }
            "small_10" { 10 }
            "minidev_diverse_10" { 10 }
            "formula_1_smoke_10" { 10 }
            "medium_25" { 25 }
            "big_100" { 100 }
            "full" { 500 }
            default { $null }
        }
        frameworks               = @($frameworkRuns)
        started_at               = $startedAt
        finished_at              = (Get-Date).ToString("o")
        dsn_eval                 = $(if ($evalEngine -eq "sqlite") { "sqlite:$sqliteDatabasesDir" } else { $script:EvalDsn })
        jsonl_paths_local        = @($jsonlPaths)
        cluster                  = @{
            account = (aws sts get-caller-identity --query Account --output text)
            region  = $Region
            db_ip   = $targets.DbPrivateIp
            gpu_ip  = $targets.GpuPrivateIp
            ollama  = $targets.OllamaHost
        }
        notes                    = $manifestNotes
    }

    Update-ExperimentSummary -ResultsDir $resultsDir -PyVer $pyVer
    Write-Host ("`nDone. Commit manifest.json + summary.md under results/{0}/" -f $runId) -ForegroundColor Green
}
finally {
    if (-not $KeepTunnels) { Stop-ExperimentTunnels }
}

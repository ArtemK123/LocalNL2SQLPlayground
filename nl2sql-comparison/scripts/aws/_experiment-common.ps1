$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"

$script:AllStacks = @("langchain", "dbgpt", "premsql", "vanna", "wrenai", "chat2db")
$script:DefaultStackOrder = @("langchain", "dbgpt", "premsql", "vanna", "wrenai", "chat2db")
$script:SqlStacks = @("langchain", "premsql", "vanna", "wrenai")
$script:DefaultSqlModel = "arctic-text2sql-r1-7b:q4_k_m"
$script:DefaultGeneralModel = "qwen2.5-coder:14b-instruct-q8_0"
$script:EvalDsn = "postgresql://olap:olap@127.0.0.1:55433/bird"
$script:LocalDbForwardPort = 55433
$script:TunnelStatePath = Join-Path $env:TEMP "nl2sql-experiment-tunnels.json"

function Get-OllamaModelCatalog {
    return @{
        sql     = $script:DefaultSqlModel
        general = $script:DefaultGeneralModel
    }
}

function Get-ExperimentRoot {
    return (Get-Nl2sqlComparisonRoot)
}

function Get-StackUiPortMap {
    return @{
        langchain = 8501
        dbgpt     = 5670
        premsql   = 8501
        vanna     = 8001
        wrenai    = 3001
        chat2db   = 10825
    }
}

function Get-ExperimentForwardPorts {
    # Distinct local ports for SSM/SSH forwards (UI + NL2SQL HTTP APIs).
    $ports = @((Get-StackUiPortMap).Values) + @(8011, 8012)
    return $ports | Sort-Object -Unique
}

function Get-ProjectSshHost {
    param([string] $Role)
    $project = Get-ProjectName
    return "${project}-${Role}"
}

function Get-HarnessPythonVersion {
    foreach ($ver in @("-3.13", "-3.12", "-3.11", "-3.10")) {
        try {
            & py $ver -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $ver }
        } catch { }
    }
    throw "Python 3.10+ required for nl2sql-harness (e.g. py -3.13)."
}

function Ensure-HarnessInstalled {
    $root = Get-ExperimentRoot
    $harness = Join-Path $root "harness"
    $pyVer = Get-HarnessPythonVersion
    & py $pyVer -m pip show nl2sql-comparison-harness 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing harness (editable) with py $pyVer ..."
        & py $pyVer -m pip install -e "${harness}[ui]"
        if ($LASTEXITCODE -ne 0) { throw "pip install harness failed" }
    }
    return $pyVer
}

function Get-StackModelsConfig {
    $path = Join-Path (Get-ExperimentRoot) "models\stack-models.json"
    if (-not (Test-Path $path)) { throw "Missing stack model registry: $path" }
    $data = Get-Content $path -Raw | ConvertFrom-Json
    $hash = @{}
    foreach ($prop in $data.PSObject.Properties) {
        $hash[$prop.Name] = [string]$prop.Value
    }
    return $hash
}

function Resolve-ModelProfileName {
    param([string] $ProfileOrTag)
    switch ($ProfileOrTag) {
        "general" { return $script:DefaultGeneralModel }
        "sql" { return $script:DefaultSqlModel }
        default { return $ProfileOrTag }
    }
}

function Resolve-StackModel {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Stack,
        [hashtable] $ProfileData = @{},
        [string] $SqlDefault = $script:DefaultSqlModel
    )
    if ($ProfileData.ContainsKey("stack_models") -and $ProfileData["stack_models"]) {
        $sm = $ProfileData["stack_models"]
        if ($sm -is [System.Collections.IDictionary] -and $sm.Contains($Stack)) {
            return Resolve-ModelProfileName -ProfileOrTag ([string]$sm[$Stack])
        }
        if ($sm.PSObject.Properties.Name -contains $Stack) {
            return Resolve-ModelProfileName -ProfileOrTag ([string]$sm.$Stack)
        }
    }
    $cfg = Get-StackModelsConfig
    if ($cfg.ContainsKey($Stack)) {
        $role = $cfg[$Stack]
        if ($role -eq "general") { return $script:DefaultGeneralModel }
        if ($role -eq "sql") { return $(if ($SqlDefault) { $SqlDefault } else { $script:DefaultSqlModel }) }
    }
    if ($Stack -in $script:SqlStacks) { return $SqlDefault }
    return $script:DefaultGeneralModel
}

function Resolve-StackModelsMap {
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $Stacks,
        [hashtable] $ProfileData = @{},
        [string] $SqlDefault = $script:DefaultSqlModel
    )
    $map = @{}
    foreach ($stack in $Stacks) {
        $map[$stack] = Resolve-StackModel -Stack $stack -ProfileData $ProfileData -SqlDefault $SqlDefault
    }
    return $map
}

function Get-GpuActiveModel {
    param(
        [string] $Region,
        [string] $GpuInstanceId
    )
    return & (Join-Path $PSScriptRoot "get-gpu-active-model.ps1") -Region $Region -GpuInstanceId $GpuInstanceId
}

function Assert-GpuActiveModel {
    param(
        [Parameter(Mandatory = $true)]
        [string] $ExpectedModel,
        [Parameter(Mandatory = $true)]
        [string] $Stack,
        [string] $Region,
        [switch] $SkipModelCheck
    )
    if ($SkipModelCheck) {
        Write-Warning "SkipModelCheck: not verifying GPU model for $Stack"
        return
    }
    $active = Get-GpuActiveModel -Region $Region
    if ($active -ne $ExpectedModel) {
        $profile = if ($ExpectedModel -eq $script:DefaultGeneralModel) { "general" } else { "sql" }
        Write-Warning "GPU active model '$active' != expected '$ExpectedModel' for stack '$Stack'."
        Write-Warning "Run: .\scripts\aws\set-gpu-model.ps1 -ModelProfile $profile   (or -Model '$ExpectedModel')"
        throw "GPU model mismatch for $Stack. Switch model manually before continuing."
    }
}

function Assert-GpuSqlInfrastructure {
    param(
        [string] $Region,
        [string] $GpuInstanceId,
        [string] $ExpectedInstanceType = "g6.xlarge"
    )
    $Region = Get-AwsRegion -Region $Region
    $targets = Resolve-ClusterTargets -GpuInstanceId $GpuInstanceId -Region $Region -RequireGpu -RequireDb:$false -RequireNl2sql:$false
    $row = aws ec2 describe-instances --region $Region --instance-ids $targets.GpuInstanceId `
        --query "Reservations[0].Instances[0].[InstanceType,InstanceLifecycle]" `
        --output text 2>$null
    if (-not $row -or $row -eq "None") {
        Write-Warning "Could not read GPU instance type for $($targets.GpuInstanceId)"
        return
    }
    $parts = $row -split "`t"
    $instanceType = $parts[0]
    $lifecycle = if ($parts.Count -ge 2) { $parts[1] } else { $null }
    Write-Host "GPU instance: type=$instanceType lifecycle=$(if ($lifecycle -and $lifecycle -ne 'None') { $lifecycle } else { 'on-demand' })"
    if ($lifecycle -eq "spot") {
        Write-Warning "GPU is Spot — Arctic runs can be interrupted. Set gpu_use_spot=false and terraform apply."
    }
    if ($instanceType -ne $ExpectedInstanceType) {
        Write-Warning "GPU type is '$instanceType' (recommended: $ExpectedInstanceType for LangChain+Arctic)."
    }
    $active = Get-GpuActiveModel -Region $Region -GpuInstanceId $targets.GpuInstanceId
    if ($active -eq $script:DefaultGeneralModel) {
        Write-Warning "GPU has general model (Qwen) loaded — SQL stacks need Arctic. Run: .\scripts\aws\set-gpu-model.ps1 -ModelProfile sql"
    }
}

function Ensure-GpuModelForStack {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Stack,
        [string] $Region,
        [string] $GpuInstanceId,
        [switch] $SkipGpuModelSwitch,
        [int] $TimeoutSec = 1800
    )
    if ($SkipGpuModelSwitch) {
        Write-Host "SkipGpuModelSwitch: not switching GPU model for $Stack"
        return
    }
    $profiles = Get-StackModelsConfig
    if (-not $profiles.ContainsKey($Stack)) {
        Write-Warning "No model profile for stack '$Stack' in models/stack-models.json"
        return
    }
    $profile = $profiles[$Stack]
    Write-Host "Ensuring GPU model profile '$profile' for stack '$Stack' ..."
    & (Join-Path $PSScriptRoot "set-gpu-model.ps1") `
        -ModelProfile $profile `
        -Region $Region `
        -GpuInstanceId $GpuInstanceId `
        -TimeoutSec $TimeoutSec
}

function Import-ExperimentProfile {
    param([string] $ProfilePath)
    if (-not $ProfilePath) { return @{} }
    $full = if ([System.IO.Path]::IsPathRooted($ProfilePath)) { $ProfilePath } else { Join-Path (Get-ExperimentRoot) $ProfilePath }
    if (-not (Test-Path $full)) { throw "Profile not found: $full" }
    $data = Get-Content $full -Raw | ConvertFrom-Json
    $hash = @{}
    foreach ($prop in $data.PSObject.Properties) {
        $hash[$prop.Name] = $prop.Value
    }
    return $hash
}

function Resolve-ExperimentStacks {
    param(
        [string[]] $Stacks,
        [string[]] $ExcludeStacks,
        [string[]] $ProfileStacks
    )
    $list = if ($Stacks -and $Stacks.Count -gt 0) { $Stacks } elseif ($ProfileStacks) { $ProfileStacks } else { $script:DefaultStackOrder }
    $ordered = $script:DefaultStackOrder | Where-Object { $_ -in $list }
    if ($ExcludeStacks) {
        $ordered = $ordered | Where-Object { $_ -notin $ExcludeStacks }
    }
    if (-not $ordered -or $ordered.Count -eq 0) {
        throw "No stacks selected after -Stacks / -ExcludeStacks."
    }
    return @($ordered)
}

function New-ExperimentRunId {
    param([string] $Prefix = "aws")
    return "${Prefix}_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
}

function Get-ExperimentResultsDir {
    param([string] $RunId)
    $dir = Join-Path (Get-ExperimentRoot) "results\$RunId"
    New-Item -ItemType Directory -Force -Path $dir, (Join-Path $dir "jsonl"), (Join-Path $dir "traces") | Out-Null
    return $dir
}

function Ensure-SessionManagerPluginPath {
    if (Get-Command session-manager-plugin -ErrorAction SilentlyContinue) { return }
    foreach ($dir in @(
            "$env:ProgramFiles\Amazon\SessionManagerPlugin\bin",
            "${env:ProgramFiles(x86)}\Amazon\SessionManagerPlugin\bin"
        )) {
        if (Test-Path (Join-Path $dir "session-manager-plugin.exe")) {
            $env:Path = "$dir;$env:Path"
            return
        }
    }
}

function Test-LocalTcpPort {
    param([int] $Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $Port)
        return $true
    }
    catch { return $false }
    finally { $client.Dispose() }
}

function Start-SsmPortForwardProcess {
    param(
        [string] $InstanceId,
        [int] $RemotePort,
        [int] $LocalPort,
        [string] $Region
    )
    Ensure-SessionManagerPluginPath
    if (-not (Get-Command session-manager-plugin -ErrorAction SilentlyContinue)) {
        throw "session-manager-plugin not found. Install: winget install Amazon.SessionManagerPlugin"
    }
    $argList = @(
        "ssm", "start-session",
        "--region", $Region,
        "--target", $InstanceId,
        "--document-name", "AWS-StartPortForwardingSession",
        "--parameters", "portNumber=$RemotePort,localPortNumber=$LocalPort"
    )
    $proc = Start-Process -FilePath "aws" -ArgumentList $argList -PassThru -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(30)
    $up = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        if (Test-LocalTcpPort -Port $LocalPort) { $up = $true; break }
    }
    if (-not $up) {
        if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
        throw "SSM port forward $LocalPort->$RemotePort on $InstanceId did not open local port within 30s"
    }
    return $proc
}

function Start-SshForwardProcess {
    param(
        [string] $SshExe,
        [string] $SshConfig,
        [string] $RemoteHost,
        [int[]] $LocalPorts,
        [int[]] $RemotePorts
    )
    $argList = @(
        "-F", $SshConfig, "-N",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ConnectTimeout=30"
    )
    for ($i = 0; $i -lt $LocalPorts.Count; $i++) {
        $argList += "-L", "$($LocalPorts[$i]):127.0.0.1:$($RemotePorts[$i])"
    }
    $argList += $RemoteHost
    $proc = Start-Process -FilePath $SshExe -ArgumentList $argList -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 2
    if ($proc.HasExited) {
        throw "SSH tunnel to $RemoteHost exited immediately (check PEM, bastion, write-ssh-config.ps1)"
    }
    return $proc
}

function Start-ExperimentTunnels {
    param(
        [string] $SshConfigPath,
        [string] $KeyPath,
        [int] $DbLocalPort = $script:LocalDbForwardPort,
        [ValidateSet("auto", "ssm", "ssh")]
        [string] $TunnelMode = "auto",
        [string] $Region = (Get-AwsRegion)
    )
    if (Test-Path $script:TunnelStatePath) {
        $existing = Get-Content $script:TunnelStatePath -Raw | ConvertFrom-Json
        $pids = @($existing.nl_pid, $existing.db_pid) + @($existing.nl_forward_pids) + @($existing.db_forward_pids)
        $alive = @($pids | Where-Object { $_ -and (Get-Process -Id $_ -ErrorAction SilentlyContinue) })
        if ($alive.Count -ge 1) {
            Write-Host "Reusing tunnel PIDs ($($alive.Count) process(es))"
            return $existing
        }
    }

    $targets = Resolve-ClusterTargets -Region $Region -RequireDb -RequireNl2sql
    $ports = Get-ExperimentForwardPorts
    $useSsm = $TunnelMode -eq "ssm"
    if ($TunnelMode -eq "auto") {
        Ensure-SessionManagerPluginPath
        $useSsm = $null -ne (Get-Command session-manager-plugin -ErrorAction SilentlyContinue)
        if ($useSsm) { Write-Host "Using SSM port forwarding (Session Manager plugin)." }
        else { Write-Host "Session Manager plugin missing; falling back to SSH tunnels." }
    }

    if ($useSsm) {
        $nlPids = @()
        foreach ($p in $ports) {
            Write-Host "SSM forward NL2SQL 127.0.0.1:${p} -> laptop:${p} ..."
            $nlPids += (Start-SsmPortForwardProcess -InstanceId $targets.Nl2sqlInstanceId -RemotePort $p -LocalPort $p -Region $Region).Id
        }
        Write-Host "SSM forward DB :5432 -> laptop:${DbLocalPort} ..."
        $dbPid = (Start-SsmPortForwardProcess -InstanceId $targets.DbInstanceId -RemotePort 5432 -LocalPort $DbLocalPort -Region $Region).Id
        $state = [pscustomobject]@{
            mode             = "ssm"
            nl_pid           = $nlPids[0]
            nl_forward_pids  = $nlPids
            db_pid           = $dbPid
            db_forward_pids  = @($dbPid)
            nl_instance      = $targets.Nl2sqlInstanceId
            db_instance      = $targets.DbInstanceId
            db_port          = $DbLocalPort
            started_at       = (Get-Date).ToString("o")
        }
    }
    else {
        $sshConfig = Ensure-SshConfig -SshConfigPath $SshConfigPath -KeyPath $KeyPath
        $nlHost = Get-ProjectSshHost -Role "nl2sql"
        $dbHost = Get-ProjectSshHost -Role "db"
        $sshExe = (Get-Command ssh -ErrorAction Stop).Source
        Write-Host "Starting NL2SQL UI forwards via $nlHost ..."
        $nlProc = Start-SshForwardProcess -SshExe $sshExe -SshConfig $sshConfig -RemoteHost $nlHost `
            -LocalPorts @($ports) -RemotePorts @($ports)
        Write-Host "Starting DB forward ${DbLocalPort}:5432 via $dbHost ..."
        $dbProc = Start-SshForwardProcess -SshExe $sshExe -SshConfig $sshConfig -RemoteHost $dbHost `
            -LocalPorts @($DbLocalPort) -RemotePorts @(5432)
        $state = [pscustomobject]@{
            mode        = "ssh"
            nl_pid      = $nlProc.Id
            db_pid      = $dbProc.Id
            ssh_config  = $sshConfig
            nl_host     = $nlHost
            db_host     = $dbHost
            db_port     = $DbLocalPort
            started_at  = (Get-Date).ToString("o")
        }
    }

    $state | ConvertTo-Json -Depth 4 | Set-Content -Path $script:TunnelStatePath -Encoding UTF8
    Start-Sleep -Seconds 5
    Wait-ExperimentTunnelPorts -Ports @($ports.Values) -TimeoutSec 120
    return $state
}

function Wait-ExperimentTunnelPorts {
    param(
        [int[]] $Ports,
        [int] $TimeoutSec = 90
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $pending = [System.Collections.Generic.HashSet[int]]::new([int[]]$Ports)
    while ($pending.Count -gt 0 -and (Get-Date) -lt $deadline) {
        foreach ($p in @($pending)) {
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:${p}/" -UseBasicParsing -TimeoutSec 3 -Method Head -ErrorAction Stop
                if ($r.StatusCode -ge 200) { [void]$pending.Remove($p) }
            } catch {
                if ($_.Exception.Response) { [void]$pending.Remove($p) }
            }
        }
        if ($pending.Count -gt 0) { Start-Sleep -Seconds 3 }
    }
    # At least DB port should accept TCP even if UI returns errors.
    if (-not (Test-LocalTcpPort -Port $script:LocalDbForwardPort)) {
        throw "DB tunnel not listening on 127.0.0.1:$($script:LocalDbForwardPort) (re-run with -TunnelMode ssm or fix SSH key)"
    }
    if ($pending.Count -gt 0) {
        Write-Warning "Some UI tunnel ports not yet reachable: $($pending -join ', ') (harness may retry)"
    }
}

function Stop-ExperimentTunnels {
    if (-not (Test-Path $script:TunnelStatePath)) { return }
    $state = Get-Content $script:TunnelStatePath -Raw | ConvertFrom-Json
    $allPids = @()
    foreach ($pidName in @("nl_pid", "db_pid", "pid", "nl_forward_pids", "db_forward_pids")) {
        $val = $state.$pidName
        if ($val -is [array]) { $allPids += $val } elseif ($val) { $allPids += $val }
    }
    foreach ($id in ($allPids | Select-Object -Unique)) {
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped tunnel PID $id"
    }
    Remove-Item -Force $script:TunnelStatePath -ErrorAction SilentlyContinue
}

function Invoke-StackDeployAws {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Stack,
        [string] $Region,
        [switch] $SkipPublish,
        [string] $WrenTargetTables,
        [string] $WrenTargetSchemas,
        [switch] $WrenResyncModel,
        [string] $OllamaPrimaryModel,
        [string] $OllamaFallbackModel,
        [ValidateSet("sqlite", "postgresql", "postgres", "pg")]
        [string] $ArcticSqlDialect,
        [int] $TimeoutSec = 7200
    )
    $targets = Resolve-ClusterTargets -Region $Region -RequireDb -RequireGpu -RequireNl2sql
    $bird = Get-BirdDatasetConfig
    if (-not $SkipPublish) {
        & (Join-Path $PSScriptRoot "publish-package-to-s3.ps1") -Version $bird.Version -Bucket $bird.Bucket -Region $Region
    }
    $llmBackend = if ($env:NL2SQL_LLM_BACKEND) { $env:NL2SQL_LLM_BACKEND } else { "ollama" }
    $dialect = if ($ArcticSqlDialect) {
        $ArcticSqlDialect
    } elseif ($env:ARCTIC_SQL_DIALECT) {
        $env:ARCTIC_SQL_DIALECT
    } else {
        "sqlite"
    }
    $dialect = $dialect.Trim().ToLowerInvariant()
    if ($dialect -in @("postgres", "pg", "postgresql")) { $dialect = "postgresql" } else { $dialect = "sqlite" }
    $envMap = @{
        NL2SQL_STACK         = $Stack
        BIRD_PG_HOST         = $targets.DbPrivateIp
        OLLAMA_HOST          = $targets.OllamaHost
        VLLM_BASE_URL        = $targets.OllamaHost
        LLM_BACKEND          = $llmBackend
        BIRD_DATASET_BUCKET  = $bird.Bucket
        BIRD_DATASET_VERSION = $bird.Version
        AWS_DEFAULT_REGION   = $Region
        USE_LOCAL_OLLAMA     = "false"
        SKIP_NL_SMOKE        = "true"
        ARCTIC_SQL_DIALECT   = $dialect
    }
    if ($WrenTargetTables) { $envMap["WREN_TARGET_TABLES"] = $WrenTargetTables }
    if ($WrenTargetSchemas) { $envMap["WREN_TARGET_SCHEMAS"] = $WrenTargetSchemas }
    if ($WrenResyncModel) { $envMap["WREN_RESYNC_MODEL"] = "true" }
    if ($OllamaPrimaryModel) { $envMap["OLLAMA_PRIMARY_MODEL"] = $OllamaPrimaryModel }
    if ($OllamaFallbackModel) { $envMap["OLLAMA_FALLBACK_MODEL"] = $OllamaFallbackModel }
    if ($llmBackend -eq "vllm" -and -not $OllamaPrimaryModel) {
        $envMap["OLLAMA_PRIMARY_MODEL"] = "Snowflake/Arctic-Text2SQL-R1-7B"
        $envMap["OLLAMA_FALLBACK_MODEL"] = "Snowflake/Arctic-Text2SQL-R1-7B"
    }
    if ($llmBackend -eq "vllm") {
        $envMap["OLLAMA_NUM_PREDICT"] = "512"
        $envMap["ARCTIC_SQL_FENCE_PREFILL"] = "true"
        $envMap["LLM_HTTP_TIMEOUT_SEC"] = "20"
        $envMap["SQL_REPAIR_MAX_RETRIES"] = "0"
        $envMap["NL2SQL_FAST_MODE"] = "true"
        $envMap["SCHEMA_SOURCE"] = "bird_tables"
        $envMap["SCHEMA_FINAL_TOP_K"] = "8"
        $envMap["SCHEMA_BM25_INCLUDE_FK"] = "true"
        $envMap["SCHEMA_SELECTOR_MODE"] = "bm25"
        $envMap["SQL_EXEC_MODE"] = "skip"
    }

    & (Join-Path $PSScriptRoot "invoke-ssm.ps1") `
        -InstanceId $targets.Nl2sqlInstanceId `
        -ScriptPath (Join-Path $PSScriptRoot "ssm-smoke-stack.sh") `
        -Region $Region `
        -Env $envMap `
        -TimeoutSec $TimeoutSec
}

function Start-LangchainChainlitUi {
    param([string] $Region, [int] $TimeoutSec = 600)
    $targets = Resolve-ClusterTargets -Region $Region -RequireNl2sql
    & (Join-Path $PSScriptRoot "invoke-ssm.ps1") `
        -InstanceId $targets.Nl2sqlInstanceId `
        -ScriptPath (Join-Path $PSScriptRoot "ssm-start-langchain-ui.sh") `
        -Region $Region `
        -TimeoutSec $TimeoutSec
}

function Get-WrenTargetTablesExport {
    param(
        [string] $Suite,
        [string] $PyVer,
        [string] $DbProfile = "full"
    )
    if ($DbProfile -eq "full") {
        return "*"
    }
    $root = Get-ExperimentRoot
    $script = Join-Path $root "harness\scripts\wren\generate_target_tables.py"
    $lines = & py $PyVer $script --suite $Suite --db-profile $DbProfile --scope minidev --print-export 2>&1
    $line = ($lines | Where-Object { $_ -match "^WREN_TARGET_TABLES=" } | Select-Object -First 1)
    if (-not $line) { throw "generate_target_tables.py did not emit WREN_TARGET_TABLES" }
    return ($line -replace "^WREN_TARGET_TABLES=", "").Trim()
}

function Get-WrenMinidevSchemasCsv {
    return "california_schools,card_games,codebase_community,debit_card_specializing,european_football_2,financial,formula_1,student_club,superhero,thrombosis_prediction,toxicology"
}

function Invoke-HarnessRun {
    param(
        [string] $Stack,
        [string] $Suite,
        [string] $PyVer,
        [string] $OutPath,
        [double] $Timeout,
        [ValidateSet("api", "ui")]
        [string] $Mode = "ui",
        [int] $Workers = 1,
        [string] $ApiUrl,
        [ValidateSet("postgres", "sqlite")]
        [string] $EvalEngine = "postgres",
        [string] $SqliteDatabasesDir,
        [ValidateSet("bird", "multiset")]
        [string] $ExMode = "multiset",
        [switch] $Headed,
        [switch] $Trace
    )
    # Mode=api uses HTTP /v1/chat (run-api). Chainlit/Playwright are not required —
    # callers should skip Start-LangchainChainlitUi when Mode=api (see run-benchmark-aws.ps1).
    $harness = Join-Path (Get-ExperimentRoot) "harness"
    if ($Mode -eq "api") {
        $runArgs = @(
            "run-api",
            "--framework", $Stack,
            "--suite", $Suite,
            "--timeout", [string]$Timeout
        )
        if ($EvalEngine -eq "sqlite") {
            if (-not $SqliteDatabasesDir) {
                throw "EvalEngine=sqlite requires SqliteDatabasesDir (MINIDEV/dev_databases)"
            }
            $runArgs += @(
                "--eval-engine", "sqlite",
                "--sqlite-databases-dir", $SqliteDatabasesDir,
                "--ex-mode", $ExMode,
                "--dsn", "postgresql://unused"
            )
        } else {
            $runArgs += @("--dsn", $script:EvalDsn, "--eval-engine", "postgres", "--ex-mode", $ExMode)
        }
        if ($Workers -ge 1) { $runArgs += @("--workers", [string]$Workers) }
        if ($ApiUrl) { $runArgs += @("--api-url", $ApiUrl) }
        if ($OutPath) { $runArgs += @("--out", $OutPath) }
        # headed / --trace are UI-only; omit for API
    }
    else {
        $runArgs = @(
            "run",
            "--framework", $Stack,
            "--suite", $Suite,
            "--dsn", $script:EvalDsn,
            "--resources", "none",
            "--timeout", [string]$Timeout
        )
        if ($Headed) { $runArgs += "--headed" }
        if ($Trace) { $runArgs += "--trace" }
        if ($OutPath) { $runArgs += @("--out", $OutPath) }
    }

    Push-Location $harness
    try {
        & py $PyVer -m nl2sql_comparison_harness @runArgs
        if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "harness run failed ($LASTEXITCODE)" }
    }
    finally {
        Pop-Location
    }
}

function Get-JsonlAverageLatencyMs {
    param([string] $JsonlPath)
    if (-not (Test-Path $JsonlPath)) { return $null }
    $vals = @()
    foreach ($line in Get-Content $JsonlPath) {
        if (-not $line.Trim()) { continue }
        $row = $line | ConvertFrom-Json
        if ($null -ne $row.latency_ms) { $vals += [double]$row.latency_ms }
    }
    if ($vals.Count -eq 0) { return $null }
    return ($vals | Measure-Object -Average).Average
}

function Write-ExperimentManifest {
    param(
        [string] $ResultsDir,
        [hashtable] $Fields
    )
    $manifestPath = Join-Path $ResultsDir "manifest.json"
    $obj = [ordered]@{}
    foreach ($key in ($Fields.Keys | Sort-Object)) {
        $obj[$key] = $Fields[$key]
    }
    ($obj | ConvertTo-Json -Depth 6) | Set-Content -Path $manifestPath -Encoding UTF8
    Write-Host "Wrote $manifestPath"
}

function Update-ExperimentSummary {
    param(
        [string] $ResultsDir,
        [string] $PyVer
    )
    $jsonlDir = Join-Path $ResultsDir "jsonl"
    $files = Get-ChildItem $jsonlDir -Filter "*.jsonl" -ErrorAction SilentlyContinue
    $lines = @(
        "# NL2SQL AWS experiment summary",
        "",
        "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        ""
    )
    foreach ($f in $files) {
        $lines += "## $($f.BaseName)"
        $lines += ""
        $summary = & py $PyVer -m nl2sql_comparison_harness summarize $f.FullName --table 2>&1
        $lines += ($summary -split "`n")
        $lines += ""
    }
    $summaryPath = Join-Path $ResultsDir "summary.md"
    $lines -join "`n" | Set-Content -Path $summaryPath -Encoding UTF8
    Write-Host "Wrote $summaryPath"
}

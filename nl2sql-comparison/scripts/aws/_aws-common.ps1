$ErrorActionPreference = "Stop"

function Get-Nl2sqlComparisonRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Get-TerraformComputeDir {
    return Join-Path (Get-Nl2sqlComparisonRoot) "terraform\compute"
}

function Get-TfvarsPath {
    return Join-Path (Get-TerraformComputeDir) "terraform.tfvars"
}

function Get-Tfvar {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Name,
        [string] $TfvarsPath = (Get-TfvarsPath)
    )
    if (-not (Test-Path $TfvarsPath)) { return $null }
    foreach ($line in Get-Content $TfvarsPath) {
        if ($line -match "^\s*${Name}\s*=\s*""([^""]+)""") { return $Matches[1] }
        if ($line -match "^\s*${Name}\s*=\s*(\S+)") { return $Matches[1].Trim('"') }
    }
    return $null
}

function Ensure-AwsCli {
    aws sts get-caller-identity | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "AWS credentials not active. Run: aws sso login"
    }
}

function Get-AwsRegion {
    param([string] $Region)
    if ($Region) { return $Region }
    $fromTf = Get-Tfvar -Name "aws_region"
    if ($fromTf) { return $fromTf }
    return "us-east-1"
}

function Export-AwsCredentialsFromCli {
    $c = aws configure export-credentials --output json 2>$null | ConvertFrom-Json
    if ($c.AccessKeyId) {
        $env:AWS_ACCESS_KEY_ID = $c.AccessKeyId
        $env:AWS_SECRET_ACCESS_KEY = $c.SecretAccessKey
        $env:AWS_SESSION_TOKEN = $c.SessionToken
    }
}

function Get-TerraformOutputs {
    param([switch] $RefreshCredentials)
    if ($RefreshCredentials) { Export-AwsCredentialsFromCli }
    $tfDir = Get-TerraformComputeDir
    $json = terraform -chdir="$tfDir" output -json 2>$null
    if (-not $json) { throw "terraform output failed. Apply compute module first." }
    return ($json | ConvertFrom-Json)
}

function Get-ProjectName {
    $project = Get-Tfvar -Name "project_name"
    if ($project) { return $project }
    return "nl2sql-comparison"
}

function Get-Ec2InstanceRecord {
    param(
        [Parameter(Mandatory = $true)]
        [string] $NameTag,
        [string] $Region = (Get-AwsRegion),
        [string] $PreferredInstanceId
    )
    if ($PreferredInstanceId) {
        $row = aws ec2 describe-instances --region $Region --instance-ids $PreferredInstanceId `
            --query "Reservations[0].Instances[0].[InstanceId,State.Name,PrivateIpAddress,InstanceLifecycle]" `
            --output text 2>$null
        if ($row -and $row -ne "None") {
            $parts = $row -split "`t"
            if ($parts.Count -ge 2 -and $parts[1] -in @("running", "pending")) {
                return [pscustomobject]@{
                    NameTag    = $NameTag
                    InstanceId = $parts[0]
                    State      = $parts[1]
                    PrivateIp  = if ($parts.Count -ge 3) { $parts[2] } else { $null }
                    Lifecycle  = if ($parts.Count -ge 4) { $parts[3] } else { $null }
                }
            }
        }
    }
    $json = aws ec2 describe-instances --region $Region `
        --filters "Name=tag:Name,Values=$NameTag" `
        --query "Reservations[].Instances[] | sort_by(@, &LaunchTime) | [-1]" `
        --output json 2>$null
    if (-not $json -or $json -eq "null") { return $null }
    $inst = $json | ConvertFrom-Json
    if (-not $inst) { return $null }
    return [pscustomobject]@{
        NameTag    = $NameTag
        InstanceId = $inst.InstanceId
        State      = $inst.State.Name
        PrivateIp  = $inst.PrivateIpAddress
        Lifecycle  = $inst.InstanceLifecycle
    }
}

function Get-Ec2InstanceIdByName {
    param(
        [Parameter(Mandatory = $true)]
        [string] $NameTag,
        [string] $Region = (Get-AwsRegion)
    )
    $rec = Get-Ec2InstanceRecord -NameTag $NameTag -Region $Region
    if (-not $rec -or $rec.State -notin @("running", "pending")) {
        $state = if ($rec) { $rec.State } else { "missing" }
        throw "No running instance with tag Name=$NameTag in $Region (state=$state). Spot may have terminated it - run: cd nl2sql-comparison/terraform/compute; terraform apply -auto-approve"
    }
    return $rec.InstanceId
}

function Get-ClusterInstanceStates {
    param([string] $Region = (Get-AwsRegion))
    $project = Get-ProjectName
    $roles = @(
        @{ Role = "bastion"; Name = "$project-bastion"; Required = $false }
        @{ Role = "db"; Name = "$project-db"; Required = $true }
        @{ Role = "gpu"; Name = "$project-gpu"; Required = $true }
        @{ Role = "nl2sql"; Name = "$project-nl2sql"; Required = $true }
    )
    $rows = foreach ($r in $roles) {
        $rec = Get-Ec2InstanceRecord -NameTag $r.Name -Region $Region
        [pscustomobject]@{
            Role       = $r.Role
            Name       = $r.Name
            Required   = $r.Required
            InstanceId = if ($rec) { $rec.InstanceId } else { $null }
            State      = if ($rec) { $rec.State } else { "missing" }
            PrivateIp  = if ($rec) { $rec.PrivateIp } else { $null }
            Lifecycle  = if ($rec) { $rec.Lifecycle } else { $null }
            Ready      = ($rec -and $rec.State -in @("running", "pending"))
        }
    }
    return $rows
}

function Ensure-ClusterInstances {
    <#
      Verifies required EC2 roles exist and are running/pending before deploy/smoke.
      Does not wait for SSM or application health - only instance presence.
    #>
    param(
        [string] $Region = (Get-AwsRegion),
        [switch] $RequireBastion,
        [switch] $RequireDb,
        [switch] $RequireGpu,
        [switch] $RequireNl2sql,
        [switch] $Quiet
    )
    if (-not ($RequireBastion -or $RequireDb -or $RequireGpu -or $RequireNl2sql)) {
        $RequireDb = $true
        $RequireGpu = $true
        $RequireNl2sql = $true
    }
    $states = Get-ClusterInstanceStates -Region $Region
    if (-not $Quiet) {
        $states | Format-Table Role, Name, State, PrivateIp, Lifecycle, Ready -AutoSize
    }
    $need = @()
    foreach ($s in $states) {
        $required = ($s.Role -eq "bastion" -and $RequireBastion) `
            -or ($s.Role -eq "db" -and $RequireDb) `
            -or ($s.Role -eq "gpu" -and $RequireGpu) `
            -or ($s.Role -eq "nl2sql" -and $RequireNl2sql)
        if ($required -and -not $s.Ready) {
            $need += "$($s.Role) ($($s.Name), state=$($s.State))"
        }
    }
    if ($need.Count -gt 0) {
        $tfDir = Get-TerraformComputeDir
        throw @"
Required EC2 instance(s) not running: $($need -join '; ')

Spot instances (db/gpu/nl2sql) can disappear after interruption. Recreate compute:
  cd $tfDir
  terraform apply -auto-approve

Then redeploy roles as needed:
  .\scripts\aws\deploy-db-from-s3.ps1 -SkipUpload
  .\scripts\aws\deploy-gpu-from-s3.ps1 -SkipPublish
"@
    }
    if (-not $Quiet) {
        Write-Host "Cluster EC2 preflight OK (all required instances running/pending)."
    }
}

function Resolve-ClusterTargets {
    param(
        [string] $DbInstanceId,
        [string] $GpuInstanceId,
        [string] $Nl2sqlInstanceId,
        [string] $Region = (Get-AwsRegion),
        [switch] $RequireDb,
        [switch] $RequireGpu,
        [switch] $RequireNl2sql,
        [switch] $RefreshCredentials
    )
    $project = Get-ProjectName

    $out = $null
    try {
        if ($RefreshCredentials) { Export-AwsCredentialsFromCli }
        $out = Get-TerraformOutputs
    }
    catch {
        Write-Host "terraform output unavailable; resolving instance IDs via EC2 API."
    }

    if (-not ($RequireDb -or $RequireGpu -or $RequireNl2sql)) {
        $RequireDb = $true
        $RequireGpu = $true
        $RequireNl2sql = $true
    }

    $tfDbId = if ($out) { $out.db_instance_id.value } else { $null }
    $tfGpuId = if ($out) { $out.gpu_instance_id.value } else { $null }
    $tfNlId = if ($out) { $out.nl2sql_instance_id.value } else { $null }

    $dbRec = $null
    $gpuRec = $null
    $nlRec = $null
    if ($RequireDb) {
        $dbRec = Get-Ec2InstanceRecord -NameTag "$project-db" -Region $Region -PreferredInstanceId $(if (-not $DbInstanceId) { $tfDbId } else { $DbInstanceId })
        if (-not $dbRec -or $dbRec.State -notin @("running", "pending")) {
            $st = if ($dbRec) { $dbRec.State } else { "missing" }
            throw "DB instance not running (state=$st). Run terraform apply in terraform/compute, then deploy-db-from-s3.ps1"
        }
        $DbInstanceId = $dbRec.InstanceId
    }
    if ($RequireGpu) {
        $gpuRec = Get-Ec2InstanceRecord -NameTag "$project-gpu" -Region $Region -PreferredInstanceId $(if (-not $GpuInstanceId) { $tfGpuId } else { $GpuInstanceId })
        if (-not $gpuRec -or $gpuRec.State -notin @("running", "pending")) {
            $st = if ($gpuRec) { $gpuRec.State } else { "missing" }
            throw "GPU instance not running (state=$st). Spot interruption is common - run: cd terraform/compute; terraform apply -auto-approve; then deploy-gpu-from-s3.ps1"
        }
        $GpuInstanceId = $gpuRec.InstanceId
    }
    if ($RequireNl2sql) {
        $nlRec = Get-Ec2InstanceRecord -NameTag "$project-nl2sql" -Region $Region -PreferredInstanceId $(if (-not $Nl2sqlInstanceId) { $tfNlId } else { $Nl2sqlInstanceId })
        if (-not $nlRec -or $nlRec.State -notin @("running", "pending")) {
            $st = if ($nlRec) { $nlRec.State } else { "missing" }
            throw "NL2SQL instance not running (state=$st). Run terraform apply in terraform/compute"
        }
        $Nl2sqlInstanceId = $nlRec.InstanceId
    }

    $dbIp = if ($dbRec) { $dbRec.PrivateIp } else { $null }
    $gpuIp = if ($gpuRec) { $gpuRec.PrivateIp } else { $null }

    $ollamaHost = if ($gpuIp -and $gpuIp -ne "None") { "http://${gpuIp}:11434" } else { $null }

    return [pscustomobject]@{
        Project          = $project
        Region           = $Region
        DbInstanceId     = $DbInstanceId
        GpuInstanceId    = $GpuInstanceId
        Nl2sqlInstanceId = $Nl2sqlInstanceId
        DbPrivateIp      = $dbIp
        GpuPrivateIp     = $gpuIp
        OllamaHost       = $ollamaHost
    }
}

function Get-BirdDatasetConfig {
    param(
        [string] $Bucket,
        [string] $Version
    )
    if (-not $Bucket) { $Bucket = Get-Tfvar -Name "bird_dataset_bucket" }
    if (-not $Version) { $Version = Get-Tfvar -Name "bird_dataset_version" }
    if (-not $Version) { $Version = (Get-Date -Format "yyyy-MM-dd") }
    if (-not $Bucket) {
        $acct = (aws sts get-caller-identity --query Account --output text)
        $Bucket = "nl2sql-comparison-bird-$acct"
    }
    return [pscustomobject]@{
        Bucket  = $Bucket
        Version = $Version
    }
}

function Get-DefaultSshKeyPath {
    param([string] $KeyPath)
    if ($KeyPath) {
        if (-not (Test-Path $KeyPath)) { throw "SSH key not found: $KeyPath" }
        return (Resolve-Path $KeyPath).Path
    }
    $awsDir = Split-Path (Get-Nl2sqlComparisonRoot) -Parent
    $default = Join-Path $awsDir "credentials\test-pair.pem"
    if (-not (Test-Path $default)) {
        throw "SSH key not found: $default (pass -KeyPath or place test-pair.pem under aws/credentials/)"
    }
    return (Resolve-Path $default).Path
}

function Get-DefaultSshConfigPath {
    param([string] $SshConfigPath)
    if ($SshConfigPath) { return $SshConfigPath }
    return Join-Path $env:USERPROFILE ".ssh\nl2sql_comparison_ssh_config"
}

function Get-StableSshKeyPath {
    <#
      Copy PEM to %USERPROFILE%\.ssh (ASCII path). OpenSSH on Windows often fails to load
      keys under Cyrillic workspace paths (identity file type -1, forwards never bind).
    #>
    param([string] $KeyPath)
    $source = Get-DefaultSshKeyPath -KeyPath $KeyPath
    $stable = Join-Path $env:USERPROFILE ".ssh\nl2sql_comparison_key.pem"
    $dir = Split-Path $stable -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $copy = $true
    if (Test-Path $stable) {
        $srcTime = (Get-Item $source).LastWriteTimeUtc
        $dstTime = (Get-Item $stable).LastWriteTimeUtc
        $copy = ($srcTime -gt $dstTime)
    }
    if ($copy) { Copy-Item -Path $source -Destination $stable -Force }
    return $stable
}

function Format-SshIdentityFile {
    param([string] $KeyPath)
    # OpenSSH splits IdentityFile on spaces unless the path is quoted.
    $normalized = ((Resolve-Path $KeyPath).Path -replace '\\', '/')
    return "`"$normalized`""
}

function Write-Nl2sqlSshConfig {
    <#
      Writes OpenSSH config for bastion ProxyJump access.
      Deploy/smoke automation uses SSM; SSH is for debug, port-forward, and optional sync-to-ec2.
    #>
    param(
        [string] $SshConfigPath,
        [string] $KeyPath,
        [switch] $Force
    )
    $configPath = Get-DefaultSshConfigPath -SshConfigPath $SshConfigPath
    if ((Test-Path $configPath) -and -not $Force) {
        return $configPath
    }

    $key = Get-StableSshKeyPath -KeyPath $KeyPath
    $identity = Format-SshIdentityFile -KeyPath $key
    $knownHosts = Join-Path $env:USERPROFILE ".ssh\nl2sql_comparison_known_hosts"
    $sshCommon = @"
  StrictHostKeyChecking accept-new
  UserKnownHostsFile "$($knownHosts -replace '\\','/')"
"@
    $out = Get-TerraformOutputs -RefreshCredentials
    $project = Get-Tfvar -Name "project_name"
    if (-not $project) { $project = "nl2sql-comparison" }

    $bastionIp = $out.bastion_public_ip.value
    $dbIp = $out.db_private_ip.value
    $gpuIp = $out.gpu_private_ip.value
    $nlIp = $out.nl2sql_private_ip.value

    $dir = Split-Path $configPath -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

    $content = @"
# Generated by scripts/aws/write-ssh-config.ps1 (do not commit).
# Automation (deploy/smoke) uses SSM; SSH is optional for debug and port-forward.

Host ${project}-*
$sshCommon

Host ${project}-bastion
  HostName $bastionIp
  User ec2-user
  IdentityFile $identity

Host ${project}-db
  HostName $dbIp
  User ec2-user
  ProxyJump ${project}-bastion
  IdentityFile $identity

Host ${project}-gpu
  HostName $gpuIp
  User ec2-user
  ProxyJump ${project}-bastion
  IdentityFile $identity

Host ${project}-nl2sql
  HostName $nlIp
  User ec2-user
  ProxyJump ${project}-bastion
  IdentityFile $identity
"@
    [System.IO.File]::WriteAllText($configPath, $content, (New-Object System.Text.UTF8Encoding $false))

    Write-Host "Wrote SSH config: $configPath (key: $key)"
    return $configPath
}

function Ensure-SshConfig {
    param(
        [string] $SshConfigPath,
        [string] $KeyPath
    )
    $path = Get-DefaultSshConfigPath -SshConfigPath $SshConfigPath
    if (-not (Test-Path $path)) {
        return (Write-Nl2sqlSshConfig -SshConfigPath $path -KeyPath $KeyPath)
    }
    return $path
}

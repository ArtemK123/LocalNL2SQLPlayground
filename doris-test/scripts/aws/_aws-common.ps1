$ErrorActionPreference = "Stop"

function Get-DorisTestRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Get-TerraformComputeDir {
    return Join-Path (Get-DorisTestRoot) "terraform\compute"
}

function Get-TfvarsPath {
    return Join-Path (Get-TerraformComputeDir) "terraform.tfvars"
}

function Get-Tfvar {
    param([Parameter(Mandatory = $true)][string] $Name, [string] $TfvarsPath = (Get-TfvarsPath))
    if (-not (Test-Path $TfvarsPath)) { return $null }
    foreach ($line in Get-Content $TfvarsPath) {
        if ($line -match "^\s*${Name}\s*=\s*""([^""]+)""") { return $Matches[1] }
        if ($line -match "^\s*${Name}\s*=\s*(\S+)") { return $Matches[1].Trim('"') }
    }
    return $null
}

function Ensure-AwsCli {
    aws sts get-caller-identity | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "AWS credentials not active." }
}

function Get-AwsRegion {
    param([string] $Region)
    if ($Region) { return $Region }
    $fromTf = Get-Tfvar -Name "aws_region"
    if ($fromTf) { return $fromTf }
    return "us-east-1"
}

function Get-TerraformOutputs {
    $json = terraform -chdir="$(Get-TerraformComputeDir)" output -json 2>$null
    if (-not $json) { throw "terraform output failed. Apply compute module first." }
    return ($json | ConvertFrom-Json)
}

function Get-ProjectName {
    $p = Get-Tfvar -Name "project_name"
    if ($p) { return $p }
    return "doris-test"
}

function Get-Ec2InstanceRecord {
    param(
        [Parameter(Mandatory = $true)][string] $NameTag,
        [string] $Region = (Get-AwsRegion),
        [string] $PreferredInstanceId
    )
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($PreferredInstanceId) {
            $row = aws ec2 describe-instances --region $Region --instance-ids $PreferredInstanceId `
                --query "Reservations[0].Instances[0].[InstanceId,State.Name,PrivateIpAddress]" --output text 2>$null
            if ($row -and $row -ne "None") {
                $parts = $row -split "`t"
                if ($parts.Count -ge 2 -and $parts[1] -in @("running", "pending")) {
                    return [pscustomobject]@{ NameTag = $NameTag; InstanceId = $parts[0]; State = $parts[1]; PrivateIp = $parts[2] }
                }
            }
        }
        $json = aws ec2 describe-instances --region $Region `
            --filters "Name=tag:Name,Values=$NameTag" `
            --query "Reservations[].Instances[] | sort_by(@, &LaunchTime) | [-1]" --output json 2>$null
    } finally {
        $ErrorActionPreference = $prevEap
    }
    if (-not $json -or $json -eq "null") { return $null }
    $inst = $json | ConvertFrom-Json
    if (-not $inst) { return $null }
    return [pscustomobject]@{
        NameTag    = $NameTag
        InstanceId = $inst.InstanceId
        State      = $inst.State.Name
        PrivateIp  = $inst.PrivateIpAddress
    }
}

function Get-ClusterInstanceStates {
    param([string] $Region = (Get-AwsRegion))
    $project = Get-ProjectName
    $roles = @("bastion", "db", "gpu", "analytics", "nl2sql")
    foreach ($role in $roles) {
        $name = "$project-$role"
        $rec = Get-Ec2InstanceRecord -NameTag $name -Region $Region
        [pscustomobject]@{
            Role       = $role
            Name       = $name
            InstanceId = if ($rec) { $rec.InstanceId } else { $null }
            State      = if ($rec) { $rec.State } else { "missing" }
            PrivateIp  = if ($rec) { $rec.PrivateIp } else { $null }
            Ready      = ($rec -and $rec.State -in @("running", "pending"))
        }
    }
}

function Ensure-ClusterInstances {
    param([string] $Region = (Get-AwsRegion), [switch] $Quiet)
    $states = @(Get-ClusterInstanceStates -Region $Region)
    if (-not $Quiet) { $states | Format-Table -AutoSize }
    $bad = $states | Where-Object { $_.Role -ne "bastion" -and -not $_.Ready }
    if ($bad) {
        throw "Required instances not running: $($bad.Role -join ', '). Run: cd aws/doris-test/terraform/compute; terraform apply"
    }
}

function Resolve-ClusterTargets {
    param(
        [string] $Region = (Get-AwsRegion),
        [switch] $RefreshCredentials
    )
    if ($RefreshCredentials) {
        $c = aws configure export-credentials --output json 2>$null | ConvertFrom-Json
        if ($c.AccessKeyId) {
            $env:AWS_ACCESS_KEY_ID = $c.AccessKeyId
            $env:AWS_SECRET_ACCESS_KEY = $c.SecretAccessKey
            $env:AWS_SESSION_TOKEN = $c.SessionToken
        }
    }
    $out = Get-TerraformOutputs
    $project = Get-ProjectName
    $db = Get-Ec2InstanceRecord -NameTag "$project-db" -PreferredInstanceId $out.db_instance_id.value -Region $Region
    $gpu = Get-Ec2InstanceRecord -NameTag "$project-gpu" -PreferredInstanceId $out.gpu_instance_id.value -Region $Region
    $an = Get-Ec2InstanceRecord -NameTag "$project-analytics" -PreferredInstanceId $out.analytics_instance_id.value -Region $Region
    $nl = Get-Ec2InstanceRecord -NameTag "$project-nl2sql" -PreferredInstanceId $out.nl2sql_instance_id.value -Region $Region
    return [pscustomobject]@{
        Project             = $project
        Region              = $Region
        DbInstanceId        = $db.InstanceId
        GpuInstanceId       = $gpu.InstanceId
        AnalyticsInstanceId = $an.InstanceId
        Nl2sqlInstanceId    = $nl.InstanceId
        DbPrivateIp         = $db.PrivateIp
        GpuPrivateIp        = $gpu.PrivateIp
        AnalyticsPrivateIp  = $an.PrivateIp
        Nl2sqlPrivateIp     = $nl.PrivateIp
        OllamaHost          = "http://$($gpu.PrivateIp):11434"
        DorisFeHost         = $an.PrivateIp
    }
}

function Get-PackageDatasetConfig {
    param([string] $Bucket, [string] $Version)
    if (-not $Bucket) { $Bucket = Get-Tfvar -Name "bird_dataset_bucket" }
    if (-not $Version) { $Version = Get-Tfvar -Name "bird_dataset_version" }
    if (-not $Version) { $Version = (Get-Date -Format "yyyy-MM-dd") }
    if (-not $Bucket) {
        $acct = (aws sts get-caller-identity --query Account --output text)
        $Bucket = "doris-test-bird-$acct"
    }
    $prefix = Get-Tfvar -Name "bird_dataset_prefix"
    if (-not $prefix) { $prefix = "doris-test/package" }
    return [pscustomobject]@{ Bucket = $Bucket; Prefix = $prefix; Version = $Version }
}

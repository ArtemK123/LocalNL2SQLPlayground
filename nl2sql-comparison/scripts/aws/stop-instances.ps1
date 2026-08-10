<#
.SYNOPSIS
  Stop nl2sql-comparison EC2 instances without terminating or terraform destroy.
  Preserves EBS root volumes (and Docker/HF caches on GPU) for a warm next start.

.DESCRIPTION
  Unlike stop-system.ps1 (which runs terraform destroy), this only calls
  ec2 stop-instances for bastion/db/gpu/nl2sql. Instances become state=stopped.
#>
param(
    [string] $Region,
    [switch] $IncludeBastion,
    [switch] $SkipComposeDown,
    [string] $SshConfigPath,
    [string] $KeyPath,
    [int] $WaitTimeoutSec = 600
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
Ensure-AwsCli
$Region = Get-AwsRegion -Region $Region
$project = Get-ProjectName

$roles = @("db", "gpu", "nl2sql")
if ($IncludeBastion) { $roles = @("bastion") + $roles }

$ids = @()
foreach ($role in $roles) {
    $name = "$project-$role"
    $rec = Get-Ec2InstanceRecord -NameTag $name -Region $Region
    if (-not $rec -or -not $rec.InstanceId) {
        Write-Warning "No instance for $name - skip"
        continue
    }
    $state = $rec.State
    Write-Host "$name $($rec.InstanceId) state=$state"
    if ($state -in @("running", "pending")) {
        $ids += $rec.InstanceId
    }
    elseif ($state -eq "stopped") {
        Write-Host "  already stopped"
    }
    else {
        Write-Warning "  unexpected state=$state (not stopping)"
    }
}

if (-not $SkipComposeDown -and $ids.Count -gt 0) {
    try {
        $SshConfigPath = Ensure-SshConfig -SshConfigPath $SshConfigPath -KeyPath $KeyPath
    }
    catch {
        Write-Host "SSH config unavailable; skipping compose down ($_)."
        $SshConfigPath = $null
    }
    if ($SshConfigPath -and (Test-Path $SshConfigPath)) {
        foreach ($sshHost in @("$project-gpu", "$project-nl2sql", "$project-db")) {
            Write-Host "docker compose down on $sshHost (best-effort) ..."
            # Remote bash; keep PS-safe quoting (no &&/|| in the PowerShell source line).
            $remote = 'cd ~/nl2sql-comparison/compose 2>/dev/null; docker compose -f docker-compose.gpu.vllm.yml down; docker compose -f docker-compose.gpu.yml down; docker compose down; true'
            ssh -F $SshConfigPath $sshHost $remote 2>$null | Out-Null
        }
    }
}

if ($ids.Count -eq 0) {
    Write-Host "Nothing to stop."
    exit 0
}

Write-Host "Stopping instances (NOT terminate): $($ids -join ', ')"
aws ec2 stop-instances --region $Region --instance-ids @ids | Out-Null
if ($LASTEXITCODE -ne 0) { throw "ec2 stop-instances failed" }

$deadline = (Get-Date).AddSeconds($WaitTimeoutSec)
do {
    Start-Sleep -Seconds 10
    $states = aws ec2 describe-instances --region $Region --instance-ids @ids `
        --query "Reservations[].Instances[].[InstanceId,State.Name,Tags[?Key=='Name']|[0].Value]" `
        --output text
    Write-Host $states
    $pending = @($states -split "`n" | Where-Object { $_ -match "\b(stopping|pending|running)\b" })
} while ($pending.Count -gt 0 -and (Get-Date) -lt $deadline)

aws ec2 describe-instances --region $Region --instance-ids @ids `
    --query "Reservations[].Instances[].[Tags[?Key=='Name']|[0].Value,InstanceId,State.Name]" `
    --output table
$bad = aws ec2 describe-instances --region $Region --instance-ids @ids `
    --query "Reservations[].Instances[?State.Name!='stopped'].[InstanceId,State.Name]" `
    --output text
if ($bad) {
    throw "Some instances not stopped: $bad"
}
Write-Host "All targeted instances are stopped (not terminated). HF/docker volumes on root EBS retained."

param(
    [switch] $SkipComposeDown,
    [string] $SshConfigPath,
    [string] $KeyPath
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
$root = Get-Nl2sqlComparisonRoot
$tfCompute = Get-TerraformComputeDir

if (-not $SkipComposeDown) {
    try {
        $SshConfigPath = Ensure-SshConfig -SshConfigPath $SshConfigPath -KeyPath $KeyPath
    }
    catch {
        Write-Host "SSH config unavailable; skipping compose down on hosts ($_)."
        $SshConfigPath = $null
    }
}

if (-not $SkipComposeDown -and $SshConfigPath -and (Test-Path $SshConfigPath)) {
    foreach ($sshHost in @("nl2sql-comparison-gpu", "nl2sql-comparison-nl2sql", "nl2sql-comparison-db")) {
        Write-Host "docker compose down on $sshHost (optional) ..."
        ssh -F $SshConfigPath $sshHost "cd ~/nl2sql-comparison/compose 2>/dev/null && docker compose down || true" 2>$null
    }
}

Push-Location $tfCompute
terraform destroy -auto-approve
Pop-Location

Write-Host "Compute destroyed. Persistent EBS (terraform/persistent) and S3 objects retained."

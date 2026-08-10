param(
    [string] $SshConfigPath,
    [string] $KeyPath,
    [string] $PackageRoot = ""
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"

$SshConfigPath = Ensure-SshConfig -SshConfigPath $SshConfigPath -KeyPath $KeyPath
Get-DefaultSshKeyPath -KeyPath $KeyPath | Out-Null

if (-not $PackageRoot) {
    $PackageRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Sync-TarStream {
    param(
        [string] $TargetHost,
        [string] $RemoteDir
    )
    $cmd = @"
cd '$PackageRoot'; tar -czf - . | ssh -F '$SshConfigPath' $TargetHost "mkdir -p $RemoteDir && tar -xzf - -C $RemoteDir"
"@
    Write-Host "Syncing package to ${TargetHost}:${RemoteDir} ..."
    powershell -NoProfile -Command $cmd
    if ($LASTEXITCODE -ne 0) { throw "Sync failed for $TargetHost" }
}

# Host aliases: use names from `terraform output ssh_config_snippet` (default project_name=nl2sql-comparison).
foreach ($sshHost in @("nl2sql-comparison-db", "nl2sql-comparison-gpu", "nl2sql-comparison-nl2sql")) {
    Sync-TarStream -TargetHost $sshHost -RemoteDir "/home/ec2-user/nl2sql-comparison"
}

Write-Host "Sync complete. Package root: $PackageRoot"

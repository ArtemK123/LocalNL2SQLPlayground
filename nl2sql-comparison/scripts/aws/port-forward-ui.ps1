<#
.SYNOPSIS
  Forward an NL2SQL stack UI port from the cluster to localhost (SSM preferred, SSH fallback).

.EXAMPLE
  .\scripts\aws\port-forward-ui.ps1 -Stack chat2db
  # Open http://127.0.0.1:10825/ — leave this window open while using the UI.

.EXAMPLE
  .\scripts\aws\port-forward-ui.ps1 -Stack chat2db -TunnelMode ssh
#>
param(
    [ValidateSet("langchain", "dbgpt", "premsql", "vanna", "wrenai", "chat2db")]
    [string] $Stack = "chat2db",

    [int] $LocalPort = 0,
    [ValidateSet("auto", "ssm", "ssh")]
    [string] $TunnelMode = "auto",
    [string] $SshConfigPath,
    [string] $KeyPath,
    [string] $Region,
    [switch] $Stop
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_experiment-common.ps1"
Ensure-AwsCli
$Region = Get-AwsRegion -Region $Region

$statePath = Join-Path $env:TEMP "nl2sql-ui-forward-$Stack.json"
$ports = Get-StackUiPortMap
if ($LocalPort -le 0) { $LocalPort = $ports[$Stack] }
$remotePort = $ports[$Stack]

if ($Stop) {
    if (-not (Test-Path $statePath)) {
        Write-Host "No tunnel state for stack=$Stack ($statePath)"
        return
    }
    $state = Get-Content $statePath -Raw | ConvertFrom-Json
    Stop-Process -Id $state.pid -Force -ErrorAction SilentlyContinue
    Remove-Item -Force $statePath -ErrorAction SilentlyContinue
    Write-Host "Stopped UI tunnel for $Stack (local port $LocalPort)"
    return
}

if (Test-Path $statePath) {
    $existing = Get-Content $statePath -Raw | ConvertFrom-Json
    if (Get-Process -Id $existing.pid -ErrorAction SilentlyContinue) {
        if (Test-LocalTcpPort -Port $LocalPort) {
            Write-Host "Tunnel already running (PID $($existing.pid)). Open: http://127.0.0.1:${LocalPort}/"
            return
        }
    }
    Remove-Item -Force $statePath -ErrorAction SilentlyContinue
}

Ensure-ClusterInstances -Region $Region -RequireNl2sql
$targets = Resolve-ClusterTargets -Region $Region -RequireNl2sql

$useSsm = $TunnelMode -eq "ssm"
if ($TunnelMode -eq "auto") {
    Ensure-SessionManagerPluginPath
    $useSsm = $null -ne (Get-Command session-manager-plugin -ErrorAction SilentlyContinue)
    if ($useSsm) { Write-Host "Using SSM port forward (no SSH config required)." }
    else { Write-Host "Session Manager plugin not found; using SSH (run write-ssh-config.ps1 -Force if SSH fails)." }
}

if ($useSsm) {
    Write-Host "Forwarding NL2SQL 127.0.0.1:${remotePort} -> laptop:${LocalPort} (instance $($targets.Nl2sqlInstanceId)) ..."
    $proc = Start-SsmPortForwardProcess -InstanceId $targets.Nl2sqlInstanceId -RemotePort $remotePort -LocalPort $LocalPort -Region $Region
    $mode = "ssm"
}
else {
    $sshConfig = Write-Nl2sqlSshConfig -SshConfigPath $SshConfigPath -KeyPath $KeyPath -Force
    $nlHost = Get-ProjectSshHost -Role "nl2sql"
    $sshExe = (Get-Command ssh -ErrorAction Stop).Source
    Write-Host "SSH forward via $nlHost ..."
    $proc = Start-SshForwardProcess -SshExe $sshExe -SshConfig $sshConfig -RemoteHost $nlHost `
        -LocalPorts @($LocalPort) -RemotePorts @($remotePort)
    $mode = "ssh"
}

@{
    stack       = $Stack
    mode        = $mode
    pid         = $proc.Id
    local_port  = $LocalPort
    remote_port = $remotePort
    instance_id = $targets.Nl2sqlInstanceId
    started_at  = (Get-Date).ToString("o")
} | ConvertTo-Json | Set-Content -Path $statePath -Encoding UTF8

$url = "http://127.0.0.1:${LocalPort}/"
Write-Host ""
Write-Host "UI tunnel ready: $url" -ForegroundColor Green
Write-Host "PID $($proc.Id) - tunnel runs in background; re-run this script if the port stops responding."
Write-Host "  .\scripts\aws\port-forward-ui.ps1 -Stack $Stack"
Write-Host "Stop: .\scripts\aws\port-forward-ui.ps1 -Stack $Stack -Stop"
Write-Host ""

try {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10 -Method Head
    Write-Host "Health check: HTTP $($r.StatusCode)"
} catch {
    if ($_.Exception.Response) {
        Write-Host "Health check: HTTP $([int]$_.Exception.Response.StatusCode) (UI reachable)"
    } else {
        Write-Warning "Tunnel is up but HTTP probe failed: $($_.Exception.Message)"
    }
}

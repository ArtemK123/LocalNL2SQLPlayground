param(
    [Parameter(Mandatory = $true)][string] $InstanceId,
    [Parameter(Mandatory = $true)][string] $ScriptPath,
    [hashtable] $Env = @{},
    [string] $Region,
    [int] $TimeoutSec = 3600
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
if (-not $Region) { $Region = Get-AwsRegion }

$root = Get-DorisTestRoot
$fullScriptPath = if ([System.IO.Path]::IsPathRooted($ScriptPath)) { $ScriptPath } else { Join-Path $root $ScriptPath }
$scriptBody = (Get-Content -Path $fullScriptPath -Raw) -replace "`r`n", "`n"
$exports = ($Env.GetEnumerator() | ForEach-Object { "export $($_.Key)='$($_.Value)'" }) -join "`n"
$full = "set -uxo pipefail`n$exports`n$scriptBody"

$paramPath = Join-Path $env:TEMP "doris-test-ssm-$(Get-Random).json"
$json = @{ commands = @($full) } | ConvertTo-Json -Compress
# Windows PowerShell 5.1 lacks utf8NoBOM; write UTF-8 without BOM for AWS CLI JSON.
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($paramPath, $json, $utf8NoBom)

$cmdId = aws ssm send-command --region $Region --instance-ids $InstanceId `
    --document-name "AWS-RunShellScript" --parameters "file://$($paramPath -replace '\\','/')" `
    --timeout-seconds $TimeoutSec --query "Command.CommandId" --output text

$deadline = (Get-Date).AddSeconds($TimeoutSec)
do {
    # Refresh short-lived AWS login tokens so long SSM polls do not die mid-wait.
    try {
        Remove-Item Env:AWS_ACCESS_KEY_ID, Env:AWS_SECRET_ACCESS_KEY, Env:AWS_SESSION_TOKEN, Env:AWS_CREDENTIAL_EXPIRATION -ErrorAction SilentlyContinue
        $credLines = aws configure export-credentials --format env-no-export 2>$null
        if ($LASTEXITCODE -eq 0 -and $credLines) {
            foreach ($line in $credLines) {
                if ($line -match '^([A-Z_]+)=(.*)$') {
                    Set-Item -Path "env:$($Matches[1])" -Value $Matches[2]
                }
            }
        }
    } catch { }
    Start-Sleep -Seconds 15
    $status = aws ssm get-command-invocation --region $Region --command-id $cmdId --instance-id $InstanceId --query Status --output text
    Write-Host "Status: $status"
} while ($status -in @("Pending", "InProgress", "Delayed") -and (Get-Date) -lt $deadline)

$stdout = aws ssm get-command-invocation --region $Region --command-id $cmdId --instance-id $InstanceId --query StandardOutputContent --output text
if ($stdout) { Write-Host $stdout }
if ($status -ne "Success") { throw "SSM failed: $status" }

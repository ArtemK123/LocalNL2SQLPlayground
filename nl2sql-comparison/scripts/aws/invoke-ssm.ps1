param(
    [Parameter(Mandatory = $true)]
    [string] $InstanceId,

    [Parameter(Mandatory = $true)]
    [string] $ScriptPath,

    [hashtable] $Env = @{},
    [string] $Region,
    [int] $TimeoutSec = 3600,
    [switch] $AllowNonZeroExit
)

$ErrorActionPreference = "Stop"
# AWS CLI often writes to stderr even on success; do not treat that as a terminating error.
$PSNativeCommandUseErrorActionPreference = $false
# Avoid AWS CLI / Write-Host charmap errors on Docker progress-bar output from SSM.
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = "utf-8"
if (Test-Path (Join-Path $PSScriptRoot "_aws-common.ps1")) {
    . (Join-Path $PSScriptRoot "_aws-common.ps1")
    if (-not $Region) { $Region = Get-AwsRegion }
}
if (-not $Region) { $Region = "us-east-1" }

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$fullScriptPath = if ([System.IO.Path]::IsPathRooted($ScriptPath)) { $ScriptPath } else { Join-Path $root $ScriptPath }
$scriptBody = (Get-Content -Path $fullScriptPath -Raw) -replace "`r`n", "`n" -replace "`r", "`n"
$exports = ($Env.GetEnumerator() | ForEach-Object { "export $($_.Key)='$($_.Value)'" }) -join "`n"
$full = "set -uxo pipefail`n$exports`n$scriptBody"

$paramPath = Join-Path $env:TEMP "ssm-params-$(Get-Random).json"
$json = @{ commands = @($full) } | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText($paramPath, $json, (New-Object System.Text.UTF8Encoding $false))

$cmdId = aws ssm send-command `
    --region $Region `
    --instance-ids $InstanceId `
    --document-name "AWS-RunShellScript" `
    --parameters "file://$($paramPath -replace '\\','/')" `
    --timeout-seconds $TimeoutSec `
    --query "Command.CommandId" --output text

if (-not $cmdId) { throw "Failed to start SSM command" }
Write-Host "SSM command $cmdId on $InstanceId ..."
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$status = "Pending"
do {
    Start-Sleep -Seconds 15
    # Poll Status only — full JSON from get-command-invocation can be invalid while InProgress.
    $status = aws ssm get-command-invocation `
        --region $Region `
        --command-id $cmdId `
        --instance-id $InstanceId `
        --query "Status" `
        --output text 2>$null
    if (-not $status) { $status = "Pending" }
    Write-Host "Status: $status"
} while ($status -in @("Pending", "InProgress", "Delayed") -and (Get-Date) -lt $deadline)

# Fetch stdout/stderr via separate queries (avoids huge JSON + Windows charmap issues on docker progress output).
# AWS CLI may emit empty NativeCommandError records on Windows; never treat those as terminating.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $stdout = aws ssm get-command-invocation `
        --region $Region --command-id $cmdId --instance-id $InstanceId `
        --query "StandardOutputContent" --output text 2>$null
    $stderr = aws ssm get-command-invocation `
        --region $Region --command-id $cmdId --instance-id $InstanceId `
        --query "StandardErrorContent" --output text 2>$null
    if (-not $status) {
        $status = aws ssm get-command-invocation `
            --region $Region --command-id $cmdId --instance-id $InstanceId `
            --query "Status" --output text 2>$null
    }
} finally {
    $ErrorActionPreference = $prevEap
    $global:LASTEXITCODE = 0
}

$inv = [pscustomobject]@{
    CommandId              = $cmdId
    InstanceId             = $InstanceId
    Status                 = $status
    StandardOutputContent  = $stdout
    StandardErrorContent   = $stderr
}

Write-Host "--- STDOUT ---"
if ($stdout) { Write-Host $stdout }
if ($stderr) {
    Write-Host "--- STDERR ---"
    Write-Host $stderr
}
if ($inv.Status -ne "Success" -and -not $AllowNonZeroExit) { throw "SSM failed: $($inv.Status)" }
return $inv

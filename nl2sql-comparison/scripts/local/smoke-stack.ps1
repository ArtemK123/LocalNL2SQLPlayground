param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("langchain", "dbgpt", "premsql", "vanna", "wrenai", "chat2db")]
    [string] $Stack
)

. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = "Stop"
Ensure-ComposeEnv

function Test-HttpOk {
    param([string] $Url, [int] $Retries = 30, [int] $DelaySec = 5)
    for ($i = 1; $i -le $Retries; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400) {
                Write-Host "OK $Url ($($r.StatusCode))"
                return
            }
        }
        catch {
            Write-Host "Attempt $i/$Retries : $Url ..."
            Start-Sleep -Seconds $DelaySec
        }
    }
    throw "Health check failed: $Url"
}

$portMap = @{
    langchain = @{ Url = "http://127.0.0.1:8011/healthz"; Retries = 30 }
    dbgpt     = @{ Url = "http://127.0.0.1:8012/healthz"; Retries = 30 }
    premsql   = @{ Url = "http://127.0.0.1:8501/_stcore/health"; Retries = 45 }
    vanna     = @{ Url = "http://127.0.0.1:8001/docs"; Retries = 30 }
    wrenai    = @{ Url = "http://127.0.0.1:3001"; Retries = 60; DelaySec = 10 }
    chat2db   = @{ Url = "http://127.0.0.1:10825"; Retries = 30 }
}

$cfg = $portMap[$Stack]
$delay = if ($cfg.DelaySec) { $cfg.DelaySec } else { 5 }
Test-HttpOk -Url $cfg.Url -Retries $cfg.Retries -DelaySec $delay

if ($Stack -eq "chat2db") {
    Write-Host "Chat2DB: UI health OK. Configure Custom AI -> OLLAMA_HOST manually for NL2SQL."
}
Write-Host "smoke-stack-$Stack : OK"
exit 0

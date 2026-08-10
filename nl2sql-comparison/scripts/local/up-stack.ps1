param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("langchain", "dbgpt", "premsql", "vanna", "wrenai", "chat2db")]
    [string] $Stack,
    [switch] $Build,
    [switch] $WithUI,
    [switch] $Bootstrap,
    [switch] $WrenResyncModel
)

. "$PSScriptRoot\_common.ps1"
$file = "stacks\$Stack\docker-compose.yml"
$composeArgs = @("up", "-d")
if ($Build) { $composeArgs += "--build" }
if ($WithUI -and $Stack -eq "langchain") {
    $uiComposeArgs = @("--profile", "ui") + $composeArgs
    Invoke-Compose -ComposeFiles @($file) -ComposeCommand $uiComposeArgs
} else {
    Invoke-Compose -ComposeFiles @($file) -ComposeCommand $composeArgs
}
if ($Bootstrap -and $Stack -eq "chat2db") {
    Invoke-Compose -ComposeFiles @($file) -ComposeCommand @("run", "--rm", "chat2db-seed")
}
if ($Stack -eq "wrenai" -and ($Bootstrap -or $WrenResyncModel)) {
    if ($WrenResyncModel) { $env:WREN_RESYNC_MODEL = "true" }
    Invoke-Compose -ComposeFiles @($file) -ComposeCommand @("--profile", "wren-bootstrap", "up", "-d")
}
Write-Host "Stack $Stack up. Run: .\smoke-stack.ps1 -Stack $Stack"
if ($Stack -eq "wrenai") {
    Write-Host "Wren first-time setup or full re-index: .\up-stack.ps1 -Stack wrenai -Bootstrap" -ForegroundColor Cyan
    Write-Host "Wren re-index only (project already configured): .\up-stack.ps1 -Stack wrenai -WrenResyncModel" -ForegroundColor Cyan
}
if ($WithUI -and $Stack -eq "langchain") {
    Write-Host "Chainlit UI: http://127.0.0.1:8501 (admin/admin by default)"
}

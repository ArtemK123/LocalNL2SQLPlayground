<#
.SYNOPSIS
  Add one or more WrenAI Knowledge -> SQL pairs via GraphQL (local tunnel to :3001).

.EXAMPLE
  .\scripts\aws\add-wren-sql-pair.ps1 -Question "List German Grand Prix race names" -Sql @"
  SELECT DISTINCT r.name
  FROM races r
  JOIN circuits c ON r.circuitid = c.circuitid
  WHERE c.country = 'Germany'
  "@

.EXAMPLE
  .\scripts\aws\add-wren-sql-pair.ps1 -PairsFile stacks\wrenai\wren\sql_pairs.example.json
#>
param(
    [string] $Question,
    [string] $Sql,
    [string] $PairsFile,
    [string] $WrenUiUrl = "http://127.0.0.1:3001",
    [switch] $ListOnly,
    [switch] $NoTunnel
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

if (-not $NoTunnel) {
    & (Join-Path $PSScriptRoot "port-forward-ui.ps1") -Stack wrenai | Out-Host
}

$py = Join-Path $root "stacks\wrenai\wren\add_sql_pairs.py"
$argsList = @("--ui-wait-sec", "120")
if ($ListOnly) { $argsList += "--list" }
if ($PairsFile) { $argsList += @("--pairs-file", (Resolve-Path $PairsFile).Path) }
if ($Question -and $Sql) { $argsList += @("--question", $Question, "--sql", $Sql) }

$env:WREN_UI_URL = $WrenUiUrl
python $py @argsList

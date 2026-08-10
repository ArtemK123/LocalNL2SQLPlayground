<#!
  Stream BIRD_dev.sql into bird-postgres. See battleground_local/bird_db/load_bird_dev.ps1.
#>
param(
    [string] $SqlPath,
    [string] $Container = "bird-postgres",
    [string] $PgUser = "bird",
    [string] $PgDatabase = "bird"
)

. "$PSScriptRoot\_common.ps1"
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$resolved = Resolve-BirdDevSqlPath -SqlPath $SqlPath
Write-Host "Loading from $resolved ..."

$cmd = "docker exec -i $Container psql -U $PgUser -d $PgDatabase -v ON_ERROR_STOP=1 < `"$resolved`""
cmd.exe /c $cmd
if ($LASTEXITCODE -ne 0) { throw "psql load failed" }

docker exec $Container /bin/sh /docker-entrypoint-initdb.d/z99_grants.sh
if ($LASTEXITCODE -ne 0) { throw "z99_grants.sh failed" }
Write-Host "BIRD load complete."

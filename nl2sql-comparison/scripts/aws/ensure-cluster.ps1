<#
.SYNOPSIS
  Pre-flight: list nl2sql-comparison EC2 roles and fail if required instances are not running.

.DESCRIPTION
  Run before deploy/smoke. Spot (db/gpu/nl2sql) can terminate without updating Terraform state.
  Exit 0 when all required instances are running or pending; exit 1 otherwise.
#>
param(
    [switch] $RequireBastion,
    [switch] $SkipDb,
    [switch] $SkipGpu,
    [switch] $SkipNl2sql,
    [string] $Region
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
Ensure-AwsCli
$Region = Get-AwsRegion -Region $Region

$requireDb = -not $SkipDb
$requireGpu = -not $SkipGpu
$requireNl2sql = -not $SkipNl2sql

try {
    Ensure-ClusterInstances -Region $Region `
        -RequireBastion:$RequireBastion `
        -RequireDb:$requireDb `
        -RequireGpu:$requireGpu `
        -RequireNl2sql:$requireNl2sql
    exit 0
}
catch {
    Write-Error $_
    exit 1
}

param(
    [string] $Bucket = "",
    [string] $Version = (Get-Date -Format "yyyy-MM-dd"),
    [string] $DatasetsRoot = "",
    [string] $Region = "us-east-1"
)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
$root = Get-DorisTestRoot
if (-not $DatasetsRoot) {
    $DatasetsRoot = (Resolve-Path (Join-Path $root "..\..\datasets")).Path
}
$cfg = Get-PackageDatasetConfig -Bucket $Bucket -Version $Version
$birdSql = Join-Path $DatasetsRoot "minidev\BIRD_dev\BIRD_dev.sql"
if (-not (Test-Path $birdSql)) { throw "BIRD_dev.sql not found at $birdSql (set DATASETS_ROOT)" }
aws s3 cp $birdSql "s3://$($cfg.Bucket)/$($cfg.Prefix)/$($cfg.Version)/BIRD_dev.sql" --region $Region
Write-Host "Uploaded BIRD_dev.sql"

param([string] $Bucket = "", [string] $Version = (Get-Date -Format "yyyy-MM-dd"), [string] $Region = "us-east-1")
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
$root = Get-DorisTestRoot
$cfg = Get-PackageDatasetConfig -Bucket $Bucket -Version $Version
$tmp = Join-Path $env:TEMP "doris-test-package.tgz"
Push-Location $root
try {
    tar -czf $tmp --exclude='terraform/*/.terraform' --exclude='compose/.env' --exclude='**/__pycache__' --exclude='.git' .
}
finally { Pop-Location }
$key = "$($cfg.Prefix)/$($cfg.Version)/package.tgz"
aws s3 cp $tmp "s3://$($cfg.Bucket)/$key" --region $Region
Write-Host "Uploaded s3://$($cfg.Bucket)/$key"

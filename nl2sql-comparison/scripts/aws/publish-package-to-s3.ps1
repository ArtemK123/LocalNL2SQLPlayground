param(
    [string] $Bucket = "",
    [string] $Version = (Get-Date -Format "yyyy-MM-dd"),
    [string] $Region = "us-east-1"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

if (-not $Bucket) {
    $acct = (aws sts get-caller-identity --query Account --output text)
    $Bucket = "nl2sql-comparison-bird-$acct"
}

$tmp = Join-Path $env:TEMP "nl2sql-comparison-package.tgz"
if (Test-Path $tmp) { Remove-Item $tmp -Force }

Push-Location $root
try {
    tar -czf $tmp `
        --exclude='terraform/*/.terraform' `
        --exclude='terraform/*/terraform.tfstate*' `
        --exclude='compose/.env' `
        --exclude='**/__pycache__' `
        --exclude='harness/runs' `
        --exclude='harness/**/__pycache__' `
        --exclude='.git' `
        .
}
finally {
    Pop-Location
}

$prefix = "nl2sql-comparison/bird/$Version/package.tgz"
Write-Host "Uploading to s3://$Bucket/$prefix"
aws s3 cp $tmp "s3://$Bucket/$prefix" --region $Region
Write-Host "Done. Set bird_dataset_version=$Version in terraform/compute/terraform.tfvars"

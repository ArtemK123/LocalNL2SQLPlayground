<#
.SYNOPSIS
  Upload BIRD_dev.sql (+ manifest) to S3. EC2 DB host loads via stage-bird-assets.sh only.

.DESCRIPTION
  Operator workflow: local datasets -> S3 -> DB EC2 downloads from S3.
  Do NOT scp/rsync BIRD_dev.sql to EC2.
#>
param(
    [string] $Bucket,
    [string] $Prefix = "nl2sql-comparison/bird",
    [string] $Version = (Get-Date -Format "yyyy-MM-dd"),
    [string] $DatasetsRoot,
    [string] $SqlPath,
    [string] $Region = "us-east-1",
    [switch] $ReadBucketFromTfvars
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\..\local\_common.ps1"

function Get-Tfvar {
    param([string] $Name, [string] $TfvarsPath)
    if (-not (Test-Path $TfvarsPath)) { return $null }
    foreach ($line in Get-Content $TfvarsPath) {
        if ($line -match "^\s*${Name}\s*=\s*""([^""]+)""") { return $Matches[1] }
        if ($line -match "^\s*${Name}\s*=\s*(\S+)") { return $Matches[1] }
    }
    return $null
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$tfvars = Join-Path $root "terraform\compute\terraform.tfvars"

if ($ReadBucketFromTfvars -or -not $Bucket) {
    $fromTf = Get-Tfvar -Name "bird_dataset_bucket" -TfvarsPath $tfvars
    if ($fromTf) { $Bucket = $fromTf }
}
if (-not $Bucket) {
    $acct = (aws sts get-caller-identity --query Account --output text)
    $Bucket = "nl2sql-comparison-bird-$acct"
    Write-Host "Using default bucket: $Bucket"
}

if (-not $DatasetsRoot) { $DatasetsRoot = Get-DatasetsRoot }
$SqlPath = Resolve-BirdDevSqlPath -SqlPath $SqlPath -DatasetsRoot $DatasetsRoot
Write-Host "Using BIRD dump: $SqlPath"

$staging = Join-Path $env:TEMP "nl2sql-bird-upload-$Version"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Force -Path $staging | Out-Null
Copy-Item $SqlPath (Join-Path $staging "BIRD_dev.sql")

Push-Location $staging
try {
    $hash = (Get-FileHash "BIRD_dev.sql" -Algorithm SHA256).Hash.ToLower()
    "${hash}  BIRD_dev.sql" | Out-File -Encoding ascii "manifest.sha256"
    $uri = "s3://${Bucket}/${Prefix}/${Version}/"
    Write-Host "Uploading BIRD_dev.sql ($([math]::Round((Get-Item BIRD_dev.sql).Length / 1MB, 2)) MB) to $uri"
    aws s3 sync . $uri --region $Region
    Write-Host "Done."
    Write-Host "  s3://${Bucket}/${Prefix}/${Version}/BIRD_dev.sql"
    Write-Host "  s3://${Bucket}/${Prefix}/${Version}/manifest.sha256"
    Write-Host "Set bird_dataset_version = $Version in terraform/compute/terraform.tfvars"
    Write-Host "Deploy DB: .\scripts\aws\deploy-db-from-s3.ps1 -SkipUpload"
}
finally {
    Pop-Location
}

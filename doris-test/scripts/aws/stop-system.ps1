$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
Push-Location (Get-TerraformComputeDir)
terraform destroy -auto-approve
Pop-Location
Write-Host "Compute destroyed. Persistent EBS volumes retained in terraform/persistent."

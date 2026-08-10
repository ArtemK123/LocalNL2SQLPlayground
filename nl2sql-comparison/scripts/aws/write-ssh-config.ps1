<#
.SYNOPSIS
  Generate ~/.ssh/nl2sql_comparison_ssh_config using aws/credentials/test-pair.pem.

.DESCRIPTION
  Deploy and health smokes use SSM (preferred). SSH is optional for debugging,
  port-forwarding, and sync-to-ec2.ps1 when you want a fast tar sync without S3.
#>
param(
    [string] $SshConfigPath,
    [string] $KeyPath,
    [switch] $Force
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
Ensure-AwsCli

$path = Write-Nl2sqlSshConfig -SshConfigPath $SshConfigPath -KeyPath $KeyPath -Force:$Force
Write-Host @"

Use:
  ssh -F `"$path`" nl2sql-comparison-bastion
  ssh -F `"$path`" nl2sql-comparison-nl2sql

Port-forward (recommended - SSM, no SSH config):
  .\scripts\aws\port-forward-ui.ps1 -Stack chat2db

SSH examples (optional):
  ssh -F `"$path`" -L 10825:127.0.0.1:10825 nl2sql-comparison-nl2sql
  ssh -F `"$path`" -L 8011:127.0.0.1:8011 -L 8501:127.0.0.1:8501 nl2sql-comparison-nl2sql
"@

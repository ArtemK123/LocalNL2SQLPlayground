$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_aws-common.ps1"
$out = Get-TerraformOutputs
$project = Get-ProjectName
$bastion = $out.bastion_public_ip.value
$key = (Resolve-Path (Join-Path (Split-Path (Get-DorisTestRoot) -Parent) "credentials\test-pair.pem")).Path
$cfg = Join-Path $env:USERPROFILE ".ssh\doris_test_ssh_config"
@"
Host ${project}-bastion
  HostName $bastion
  User ec2-user
  IdentityFile $key

Host ${project}-db ${project}-gpu ${project}-analytics ${project}-nl2sql
  User ec2-user
  IdentityFile $key
  ProxyJump ${project}-bastion

Host ${project}-db
  HostName $($out.db_private_ip.value)

Host ${project}-gpu
  HostName $($out.gpu_private_ip.value)

Host ${project}-analytics
  HostName $($out.analytics_private_ip.value)

Host ${project}-nl2sql
  HostName $($out.nl2sql_private_ip.value)
"@ | Set-Content $cfg -Encoding utf8
Write-Host "Wrote $cfg"

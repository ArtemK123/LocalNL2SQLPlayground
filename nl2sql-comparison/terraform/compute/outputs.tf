output "bastion_public_ip" {
  description = "Elastic IP for SSH to bastion."
  value       = aws_eip.bastion.public_ip
}

output "db_private_ip" {
  description = "Private IP of DB host (BIRD_PG_HOST on NL2SQL host)."
  value       = aws_instance.db.private_ip
}

output "gpu_private_ip" {
  description = "Private IP of GPU host (OLLAMA_HOST=http://THIS:11434)."
  value       = aws_instance.gpu.private_ip
}

output "nl2sql_private_ip" {
  description = "Private IP of NL2SQL framework host."
  value       = aws_instance.nl2sql.private_ip
}

output "db_instance_id" {
  description = "EC2 instance ID for DB host (SSM deploy-db-from-s3.ps1)."
  value       = aws_instance.db.id
}

output "gpu_instance_id" {
  description = "EC2 instance ID for GPU host (SSM deploy-gpu-from-s3.ps1)."
  value       = aws_instance.gpu.id
}

output "nl2sql_instance_id" {
  description = "EC2 instance ID for NL2SQL host (SSM smoke-aws-stack.ps1)."
  value       = aws_instance.nl2sql.id
}

output "bird_dataset_s3_uri" {
  description = "Pinned S3 prefix used by stage-bird-assets.sh."
  value       = "s3://${var.bird_dataset_bucket}/${var.bird_dataset_prefix}/${var.bird_dataset_version}"
}

output "ssh_key_repo_path" {
  description = "EC2 key PEM in monorepo (pair with key_name=test-pair). Used by scripts/aws/write-ssh-config.ps1."
  value       = "aws/credentials/test-pair.pem"
}

output "ssh_proxyjump_command" {
  description = "Example ssh -J commands via bastion. Prefer: scripts/aws/write-ssh-config.ps1 then ssh -F ~/.ssh/nl2sql_comparison_ssh_config <host>."
  value       = <<-EOT
    # Generate config (uses aws/credentials/test-pair.pem):
    #   cd aws/nl2sql-comparison && ./scripts/aws/write-ssh-config.ps1

    ssh -F ~/.ssh/nl2sql_comparison_ssh_config ${var.project_name}-bastion
    ssh -F ~/.ssh/nl2sql_comparison_ssh_config ${var.project_name}-db
    ssh -F ~/.ssh/nl2sql_comparison_ssh_config ${var.project_name}-gpu
    ssh -F ~/.ssh/nl2sql_comparison_ssh_config ${var.project_name}-nl2sql
  EOT
}

output "ssh_config_snippet" {
  description = "Run scripts/aws/write-ssh-config.ps1 to write this with live IPs and the repo PEM path."
  value       = "See ssh_proxyjump_command output; automation uses SSM, not SSH."
}

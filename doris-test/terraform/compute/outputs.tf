output "bastion_public_ip" {
  description = "Elastic IP for SSH to bastion."
  value       = aws_eip.bastion.public_ip
}

output "db_private_ip" {
  description = "Private IP of DB host (BIRD_PG_HOST for analytics Debezium)."
  value       = aws_instance.db.private_ip
}

output "gpu_private_ip" {
  description = "Private IP of GPU host (OLLAMA_HOST)."
  value       = aws_instance.gpu.private_ip
}

output "analytics_private_ip" {
  description = "Private IP of analytics host (DORIS_FE_HOST)."
  value       = aws_instance.analytics.private_ip
}

output "nl2sql_private_ip" {
  description = "Private IP of NL2SQL host."
  value       = aws_instance.nl2sql.private_ip
}

output "db_instance_id" {
  value = aws_instance.db.id
}

output "gpu_instance_id" {
  value = aws_instance.gpu.id
}

output "analytics_instance_id" {
  value = aws_instance.analytics.id
}

output "nl2sql_instance_id" {
  value = aws_instance.nl2sql.id
}

output "bird_dataset_s3_uri" {
  description = "Pinned S3 prefix for package and BIRD artifacts."
  value       = "s3://${var.bird_dataset_bucket}/${var.bird_dataset_prefix}/${var.bird_dataset_version}"
}

output "ssh_proxyjump_command" {
  value = <<-EOT
    cd aws/doris-test && ./scripts/aws/write-ssh-config.ps1
    ssh -F ~/.ssh/doris_test_ssh_config ${var.project_name}-bastion
    ssh -F ~/.ssh/doris_test_ssh_config ${var.project_name}-db
    ssh -F ~/.ssh/doris_test_ssh_config ${var.project_name}-analytics
    ssh -F ~/.ssh/doris_test_ssh_config ${var.project_name}-gpu
    ssh -F ~/.ssh/doris_test_ssh_config ${var.project_name}-nl2sql
  EOT
}

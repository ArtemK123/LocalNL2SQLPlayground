output "db_volume_id" {
  description = "EBS for PostgreSQL PGDATA (/data/postgres on DB host)."
  value       = aws_ebs_volume.db_pgdata.id
}

output "analytics_volume_id" {
  description = "EBS for Doris BE storage (/data/doris-be on analytics host)."
  value       = aws_ebs_volume.analytics_doris_be.id
}

output "availability_zone" {
  description = "AZ where persistent volumes were created."
  value       = local.availability_zone
}

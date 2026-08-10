output "volume_id" {
  description = "Persistent EBS volume ID for BIRD PostgreSQL data."
  value       = aws_ebs_volume.bird_data.id
}

output "availability_zone" {
  description = "AZ where the persistent volume was created (pass to compute or match subnet)."
  value       = aws_ebs_volume.bird_data.availability_zone
}

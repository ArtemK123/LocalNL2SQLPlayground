variable "aws_region" {
  type        = string
  description = "AWS region."
  default     = "us-east-1"
}

variable "project_name" {
  type        = string
  description = "Prefix for resource Name tags."
  default     = "doris-test"
}

variable "availability_zone" {
  type        = string
  description = "AZ for EBS volumes (empty = first available)."
  default     = ""
}

variable "db_volume_gb" {
  type        = number
  description = "PostgreSQL BIRD data volume size."
  default     = 50
}

variable "analytics_volume_gb" {
  type        = number
  description = "Doris BE + Kafka data volume size."
  default     = 100
}

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

variable "vpc_cidr" {
  type        = string
  default     = "10.60.0.0/16"
  description = "VPC IPv4 CIDR (distinct from nl2sql-comparison 10.50.x)."
}

variable "public_subnet_cidr" {
  type        = string
  default     = "10.60.1.0/24"
  description = "Single public subnet CIDR."
}

variable "allowed_ssh_cidr" {
  type        = string
  description = "IPv4 CIDR allowed to SSH to the bastion."
}

variable "key_name" {
  type        = string
  description = "Existing EC2 key pair name in this region."
}

variable "db_persistent_volume_id" {
  type        = string
  description = "EBS volume ID from terraform/persistent (db_pgdata)."
}

variable "analytics_persistent_volume_id" {
  type        = string
  description = "EBS volume ID from terraform/persistent (analytics_doris_be)."
}

variable "bastion_instance_type" {
  type    = string
  default = "t3.micro"
}

variable "db_instance_type" {
  type    = string
  default = "c7i.xlarge"
}

variable "gpu_instance_type" {
  type    = string
  default = "g6.xlarge"
}

variable "analytics_instance_type" {
  type        = string
  description = "Kafka + Debezium + Doris host."
  default     = "r6i.xlarge"
}

variable "nl2sql_instance_type" {
  type    = string
  default = "c7i.large"
}

variable "db_root_volume_gb" {
  type    = number
  default = 30
}

variable "gpu_root_volume_gb" {
  type    = number
  default = 80
}

variable "analytics_root_volume_gb" {
  type    = number
  default = 50
}

variable "nl2sql_root_volume_gb" {
  type    = number
  default = 50
}

variable "db_use_spot" {
  type    = bool
  default = true
}

variable "gpu_use_spot" {
  type    = bool
  default = false
}

variable "analytics_use_spot" {
  type    = bool
  default = true
}

variable "nl2sql_use_spot" {
  type    = bool
  default = true
}

variable "spot_instance_interruption_behavior" {
  type    = string
  default = "terminate"
}

variable "bird_dataset_bucket" {
  type        = string
  description = "S3 bucket for BIRD artifacts and deploy package."
}

variable "bird_dataset_prefix" {
  type        = string
  description = "S3 prefix root for BIRD/package artifacts."
  default     = "doris-test/package"
}

variable "bird_dataset_version" {
  type        = string
  description = "Pinned dataset/package version path segment."
}

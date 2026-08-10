variable "aws_region" {
  type        = string
  description = "AWS region."
  default     = "us-east-1"
}

variable "project_name" {
  type        = string
  description = "Prefix for resource Name tags."
  default     = "nl2sql-comparison"
}

variable "availability_zone" {
  type        = string
  description = "AZ for the EBS volume. When empty, the first available AZ in the region is used."
  default     = ""
}

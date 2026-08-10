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

variable "vpc_cidr" {
  type        = string
  default     = "10.50.0.0/16"
  description = "VPC IPv4 CIDR."
}

variable "public_subnet_cidr" {
  type        = string
  default     = "10.50.1.0/24"
  description = "Single public subnet CIDR (one AZ, same as persistent EBS)."
}

variable "allowed_ssh_cidr" {
  type        = string
  description = "IPv4 CIDR allowed to SSH to the bastion (for example your IP /32)."
}

variable "key_name" {
  type        = string
  description = "Existing EC2 key pair name in this region."
}

variable "persistent_volume_id" {
  type        = string
  description = "EBS volume ID from terraform/persistent (aws_ebs_volume.bird_data)."
}

variable "bastion_instance_type" {
  type    = string
  default = "t3.micro"
}

variable "db_instance_type" {
  type        = string
  description = "DB host: PostgreSQL + BIRD on persistent EBS."
  default     = "c7i.xlarge"
}

variable "gpu_instance_type" {
  type        = string
  description = "GPU host for Ollama. Default g6.xlarge (L4 24 GB, 4 vCPU); g5.xlarge fallback if g6 unavailable."
  default     = "g6.xlarge"
}

variable "nl2sql_instance_type" {
  type        = string
  description = "NL2SQL host: one framework stack at a time."
  default     = "c7i.xlarge"
}

variable "db_root_volume_gb" {
  type        = number
  description = "Root EBS size for DB instance."
  default     = 30
}

variable "gpu_root_volume_gb" {
  type        = number
  description = "Root EBS size for GPU instance (vLLM image ~19GB + HF weights + docker headroom)."
  default     = 160
}

variable "nl2sql_root_volume_gb" {
  type        = number
  description = "Root EBS size for NL2SQL instance."
  default     = 80
}

variable "db_use_spot" {
  type        = bool
  description = "Whether DB instance uses Spot."
  default     = true
}

variable "gpu_use_spot" {
  type        = bool
  description = "Whether GPU instance uses Spot. false recommended for LangChain+Arctic (stable VRAM, no interruption)."
  default     = false
}

variable "nl2sql_use_spot" {
  type        = bool
  description = "Whether NL2SQL instance uses Spot."
  default     = true
}

variable "spot_instance_interruption_behavior" {
  type        = string
  description = "Spot interruption behavior for db/gpu/nl2sql instances."
  default     = "terminate"
}

variable "bird_dataset_bucket" {
  type        = string
  description = "S3 bucket that stores BIRD artifacts."
}

variable "bird_dataset_prefix" {
  type        = string
  description = "S3 prefix root for BIRD artifacts."
  default     = "nl2sql-comparison/bird"
}

variable "bird_dataset_version" {
  type        = string
  description = "Pinned BIRD dataset version path segment."
}

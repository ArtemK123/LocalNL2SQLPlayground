data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  availability_zone = var.availability_zone != "" ? var.availability_zone : data.aws_availability_zones.available.names[0]
}

resource "aws_ebs_volume" "db_pgdata" {
  availability_zone = local.availability_zone
  size              = var.db_volume_gb
  type              = "gp3"

  tags = {
    Name = "${var.project_name}-db-pgdata"
  }
}

resource "aws_ebs_volume" "analytics_doris_be" {
  availability_zone = local.availability_zone
  size              = var.analytics_volume_gb
  type              = "gp3"

  tags = {
    Name = "${var.project_name}-analytics-doris-be"
  }
}

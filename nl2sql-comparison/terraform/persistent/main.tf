data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  availability_zone = var.availability_zone != "" ? var.availability_zone : data.aws_availability_zones.available.names[0]
}

resource "aws_ebs_volume" "bird_data" {
  availability_zone = local.availability_zone
  size              = 50
  type = "gp3"

  tags = {
    Name = "nl2sql-comparison-bird-data"
  }
}

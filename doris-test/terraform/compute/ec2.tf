data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "package_read" {
  statement {
    sid    = "ListPackagePrefix"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
    ]
    resources = [
      "arn:aws:s3:::${var.bird_dataset_bucket}",
    ]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "${var.bird_dataset_prefix}/${var.bird_dataset_version}/*",
      ]
    }
  }

  statement {
    sid    = "ReadPackageObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
    ]
    resources = [
      "arn:aws:s3:::${var.bird_dataset_bucket}/${var.bird_dataset_prefix}/${var.bird_dataset_version}/*",
    ]
  }
}

resource "aws_iam_role" "ec2" {
  name_prefix        = "${var.project_name}-ec2-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json

  tags = {
    Name = "${var.project_name}-ec2-role"
  }
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_policy" "package_read" {
  name_prefix = "${var.project_name}-pkg-read-"
  policy      = data.aws_iam_policy_document.package_read.json
}

resource "aws_iam_role_policy_attachment" "package_read" {
  role       = aws_iam_role.ec2.name
  policy_arn = aws_iam_policy.package_read.arn
}

resource "aws_iam_instance_profile" "ec2" {
  name_prefix = "${var.project_name}-profile-"
  role        = aws_iam_role.ec2.name
}

locals {
  compose_install = <<-EOT
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-$(uname -m)" \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  EOT

  docker_bootstrap = <<-EOT
    dnf update -y
    dnf install -y docker awscli jq xfsprogs
    systemctl enable docker
    systemctl start docker
    usermod -aG docker ec2-user
    ${local.compose_install}
  EOT

  db_user_data = <<-EOT
    #!/bin/bash
    set -e
    ${local.docker_bootstrap}

    for i in $(seq 1 60); do
      for dev in /dev/nvme1n1 /dev/xvdf /dev/sdf; do
        if [ -b "$dev" ]; then DATA_DEV="$dev"; break 2; fi
      done
      sleep 2
    done
    if [ -z "$DATA_DEV" ]; then echo "Persistent EBS not found" >&2; exit 1; fi

    if ! blkid "$DATA_DEV" >/dev/null 2>&1; then mkfs -t xfs "$DATA_DEV"; fi
    mkdir -p /data/postgres
    if ! grep -q '/data/postgres' /etc/fstab; then
      echo "$DATA_DEV /data/postgres xfs defaults,nofail 0 2" >> /etc/fstab
    fi
    mount -a
    chmod 755 /data/postgres
  EOT

  analytics_user_data = <<-EOT
    #!/bin/bash
    set -e
    ${local.docker_bootstrap}
    sysctl -w vm.max_map_count=2000000
    echo "vm.max_map_count=2000000" >> /etc/sysctl.conf

    for i in $(seq 1 60); do
      for dev in /dev/nvme1n1 /dev/xvdf /dev/sdf; do
        if [ -b "$dev" ]; then DATA_DEV="$dev"; break 2; fi
      done
      sleep 2
    done
    if [ -z "$DATA_DEV" ]; then echo "Analytics EBS not found" >&2; exit 1; fi

    if ! blkid "$DATA_DEV" >/dev/null 2>&1; then mkfs -t xfs "$DATA_DEV"; fi
    mkdir -p /data/doris-be
    if ! grep -q '/data/doris-be' /etc/fstab; then
      echo "$DATA_DEV /data/doris-be xfs defaults,nofail 0 2" >> /etc/fstab
    fi
    mount -a
    chmod 755 /data/doris-be
  EOT

  nl2sql_user_data = <<-EOT
    #!/bin/bash
    set -e
    ${local.docker_bootstrap}
  EOT
}

resource "aws_instance" "bastion" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.bastion_instance_type
  key_name               = var.key_name
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.bastion.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  user_data = <<-EOT
    #!/bin/bash
    set -e
    dnf update -y
  EOT

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  tags = {
    Name = "${var.project_name}-bastion"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_instance" "db" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.db_instance_type
  key_name               = var.key_name
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.db.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  user_data              = local.db_user_data

  dynamic "instance_market_options" {
    for_each = var.db_use_spot ? [1] : []
    content {
      market_type = "spot"
      spot_options {
        instance_interruption_behavior = var.spot_instance_interruption_behavior
        spot_instance_type             = "one-time"
      }
    }
  }

  root_block_device {
    volume_size = var.db_root_volume_gb
    volume_type = "gp3"
  }

  tags = {
    Name = "${var.project_name}-db"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_volume_attachment" "db_pgdata" {
  device_name = "/dev/sdf"
  volume_id   = var.db_persistent_volume_id
  instance_id = aws_instance.db.id
}

resource "aws_instance" "gpu" {
  ami                    = data.aws_ami.dlami_gpu_al2023.id
  instance_type          = var.gpu_instance_type
  key_name               = var.key_name
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.gpu.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  user_data              = local.nl2sql_user_data

  dynamic "instance_market_options" {
    for_each = var.gpu_use_spot ? [1] : []
    content {
      market_type = "spot"
      spot_options {
        instance_interruption_behavior = var.spot_instance_interruption_behavior
        spot_instance_type             = "one-time"
      }
    }
  }

  root_block_device {
    volume_size = var.gpu_root_volume_gb
    volume_type = "gp3"
  }

  tags = {
    Name = "${var.project_name}-gpu"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_instance" "analytics" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.analytics_instance_type
  key_name               = var.key_name
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.analytics.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  user_data              = local.analytics_user_data

  dynamic "instance_market_options" {
    for_each = var.analytics_use_spot ? [1] : []
    content {
      market_type = "spot"
      spot_options {
        instance_interruption_behavior = var.spot_instance_interruption_behavior
        spot_instance_type             = "one-time"
      }
    }
  }

  root_block_device {
    volume_size = var.analytics_root_volume_gb
    volume_type = "gp3"
  }

  tags = {
    Name = "${var.project_name}-analytics"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_volume_attachment" "analytics_doris_be" {
  device_name = "/dev/sdf"
  volume_id   = var.analytics_persistent_volume_id
  instance_id = aws_instance.analytics.id
}

resource "aws_instance" "nl2sql" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.nl2sql_instance_type
  key_name               = var.key_name
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.nl2sql.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  user_data              = local.nl2sql_user_data

  dynamic "instance_market_options" {
    for_each = var.nl2sql_use_spot ? [1] : []
    content {
      market_type = "spot"
      spot_options {
        instance_interruption_behavior = var.spot_instance_interruption_behavior
        spot_instance_type             = "one-time"
      }
    }
  }

  root_block_device {
    volume_size = var.nl2sql_root_volume_gb
    volume_type = "gp3"
  }

  tags = {
    Name = "${var.project_name}-nl2sql"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_eip" "bastion" {
  domain = "vpc"

  tags = {
    Name = "${var.project_name}-bastion-eip"
  }
}

resource "aws_eip_association" "bastion" {
  instance_id   = aws_instance.bastion.id
  allocation_id = aws_eip.bastion.id
}

# ============================================================
# RDS SECURITY GROUP
# ============================================================

resource "aws_security_group" "rds" {
  name = "${local.name}-rds-sg"

  description = "PostgreSQL access from EKS nodes only."

  vpc_id = aws_vpc.main.id

  egress {
    description = "Allow outbound traffic."

    protocol = "-1"

    from_port = 0

    to_port = 0

    cidr_blocks = [
      "0.0.0.0/0"
    ]
  }

  tags = {
    Name = "${local.name}-rds-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_eks" {
  security_group_id = aws_security_group.rds.id

  # Managed node groups (and every pod on them, via the VPC CNI)
  # use the security group EKS creates for the cluster.
  referenced_security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id

  ip_protocol = "tcp"

  from_port = 5432

  to_port = 5432

  description = "PostgreSQL from EKS."
}

# ============================================================
# RDS SUBNET GROUP
# ============================================================

resource "aws_db_subnet_group" "main" {
  name = "${local.name}-db-subnet-group"

  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${local.name}-db-subnet-group"
  }
}

# ============================================================
# DATABASE PASSWORD
# ============================================================

resource "random_password" "database" {
  length = 32

  special = true

  override_special = "!#$%&*()-_=+[]{}<>:?"
}

# ============================================================
# RDS POSTGRESQL
# ============================================================
#
# Single-AZ intentionally.
#
# Multi-AZ is excellent for production resilience but is not
# appropriate for the $15/month target.
# ============================================================

resource "aws_db_instance" "main" {
  identifier = local.name

  engine = "postgres"

  engine_version = "17"

  instance_class = var.database_instance_class

  allocated_storage = var.database_allocated_storage

  max_allocated_storage = var.database_allocated_storage

  storage_type = "gp3"

  storage_encrypted = true

  db_name = var.database_name

  username = var.database_username

  password = random_password.database.result

  port = 5432

  db_subnet_group_name = aws_db_subnet_group.main.name

  vpc_security_group_ids = [
    aws_security_group.rds.id
  ]

  publicly_accessible = false

  multi_az = false

  backup_retention_period = 1

  auto_minor_version_upgrade = true

  deletion_protection = false

  skip_final_snapshot = true

  tags = {
    Name = local.name
  }
}

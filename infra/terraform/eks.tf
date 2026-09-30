# ============================================================
# EKS CLUSTER SECURITY GROUP
# ============================================================

resource "aws_security_group" "eks_cluster" {
  name = "${local.name}-eks-cluster-sg"

  description = "EKS control plane security group."

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
    Name = "${local.name}-eks-cluster-sg"
  }
}

# ============================================================
# EKS CLUSTER
# ============================================================

resource "aws_eks_cluster" "main" {
  name = local.name

  role_arn = aws_iam_role.eks_cluster.arn

  version = var.eks_version

  access_config {
    authentication_mode = "API_AND_CONFIG_MAP"

    bootstrap_cluster_creator_admin_permissions = true
  }

  vpc_config {
    subnet_ids = concat(
      aws_subnet.public[*].id,
      aws_subnet.private[*].id
    )

    security_group_ids = [
      aws_security_group.eks_cluster.id
    ]

    endpoint_public_access  = true
    endpoint_private_access = true
  }

  # Refuse to fall into extended support, which bills the
  # control plane at 6x the normal hourly rate.
  upgrade_policy {
    support_type = "STANDARD"
  }

  enabled_cluster_log_types = [
    "api",
    "authenticator"
  ]

  # The log group must exist first, otherwise EKS creates it
  # itself (with no retention) and Terraform fails to create it.
  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster_policy,
    aws_cloudwatch_log_group.eks
  ]

  tags = local.common_tags
}

# ============================================================
# EKS MANAGED NODE GROUP
# ============================================================

resource "aws_eks_node_group" "main" {
  cluster_name = aws_eks_cluster.main.name

  node_group_name = "${local.name}-nodes"

  node_role_arn = aws_iam_role.eks_nodes.arn

  subnet_ids = aws_subnet.public[*].id

  instance_types = var.node_instance_types

  capacity_type = "ON_DEMAND"

  disk_size = 20

  scaling_config {
    min_size = var.node_min_size

    desired_size = var.node_desired_size

    max_size = var.node_max_size
  }

  update_config {
    max_unavailable = 1
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_worker_node,
    aws_iam_role_policy_attachment.eks_cni,
    aws_iam_role_policy_attachment.eks_ecr
  ]

  tags = local.common_tags
}

# ============================================================
# CLUSTER AUTOSCALER
# ============================================================
#
# Scales the managed node group between node_min_size and
# node_max_size:
#
# - Up:   when the HPA creates backend pods that do not fit on
#         the current nodes (they sit Pending).
# - Down: when a node's requested CPU/memory stays under 50%
#         for 5 minutes and its pods fit elsewhere, it is
#         drained (respecting the backend PodDisruptionBudget)
#         and the EC2 instance is terminated.
#
# The node group's ASG is discovered by the tags EKS adds to
# every managed node group.
# ============================================================

resource "aws_iam_policy" "cluster_autoscaler" {
  name = "${local.name}-cluster-autoscaler"

  description = "IAM permissions for Cluster Autoscaler."

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "autoscaling:DescribeAutoScalingGroups",
          "autoscaling:DescribeAutoScalingInstances",
          "autoscaling:DescribeLaunchConfigurations",
          "autoscaling:DescribeScalingActivities",
          "autoscaling:DescribeTags",
          "ec2:DescribeImages",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeLaunchTemplateVersions",
          "ec2:GetInstanceTypesFromInstanceRequirements",
          "eks:DescribeNodegroup"
        ]

        Resource = "*"
      },
      {
        # Only this cluster's node groups can be resized.
        Effect = "Allow"

        Action = [
          "autoscaling:SetDesiredCapacity",
          "autoscaling:TerminateInstanceInAutoScalingGroup"
        ]

        Resource = "*"

        Condition = {
          StringEquals = {
            "aws:ResourceTag/k8s.io/cluster-autoscaler/${aws_eks_cluster.main.name}" = "owned"
          }
        }
      }
    ]
  })
}

# ============================================================
# CONTROLLER ROLE
# ============================================================

resource "aws_iam_role" "cluster_autoscaler" {
  name = "${local.name}-cluster-autoscaler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "pods.eks.amazonaws.com"
        }

        Action = [
          "sts:AssumeRole",
          "sts:TagSession"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "cluster_autoscaler" {
  role = aws_iam_role.cluster_autoscaler.name

  policy_arn = aws_iam_policy.cluster_autoscaler.arn
}

# ============================================================
# POD IDENTITY ASSOCIATION
# ============================================================

resource "aws_eks_pod_identity_association" "cluster_autoscaler" {
  cluster_name = aws_eks_cluster.main.name

  namespace = "kube-system"

  service_account = "cluster-autoscaler"

  role_arn = aws_iam_role.cluster_autoscaler.arn

  depends_on = [
    aws_eks_addon.pod_identity,
    aws_iam_role_policy_attachment.cluster_autoscaler
  ]
}

# ============================================================
# HELM RELEASE
# ============================================================

resource "helm_release" "cluster_autoscaler" {
  name = "cluster-autoscaler"

  repository = "https://kubernetes.github.io/autoscaler"

  chart = "cluster-autoscaler"

  version = "9.59.0"

  namespace = "kube-system"

  wait = true

  timeout = 600

  values = [
    yamlencode({
      cloudProvider = "aws"

      awsRegion = var.aws_region

      autoDiscovery = {
        clusterName = aws_eks_cluster.main.name
      }

      # The chart ships v1.35; the autoscaler minor version
      # should match the cluster's (eks_version 1.36). Bump
      # this together with eks_version.
      image = {
        tag = "v1.36.1"
      }

      rbac = {
        serviceAccount = {
          create = true
          name   = "cluster-autoscaler"
        }
      }

      extraArgs = {
        # Spread new nodes across both AZs.
        "balance-similar-node-groups" = true

        # Scale-down: a node is a candidate once its requests
        # stay under 50% for 5 minutes. Wait 5 minutes after a
        # scale-up before considering scale-down again.
        "scale-down-enabled"               = true
        "scale-down-utilization-threshold" = 0.5
        "scale-down-unneeded-time"         = "5m"
        "scale-down-delay-after-add"       = "5m"

        # kube-system pods (coredns, metrics-server, ...) would
        # otherwise pin every node and block scale-down.
        "skip-nodes-with-system-pods" = false

        "expander" = "least-waste"
      }

      resources = {
        requests = {
          cpu    = "25m"
          memory = "96Mi"
        }

        limits = {
          cpu    = "100m"
          memory = "256Mi"
        }
      }
    })
  ]

  depends_on = [
    aws_eks_pod_identity_association.cluster_autoscaler,
    aws_eks_addon.coredns
  ]
}

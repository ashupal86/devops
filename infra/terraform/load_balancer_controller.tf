# ============================================================
# AWS LOAD BALANCER CONTROLLER IAM POLICY
# ============================================================

resource "aws_iam_policy" "load_balancer_controller" {
  name = "${local.name}-aws-load-balancer-controller"

  description = "IAM permissions for AWS Load Balancer Controller."

  # Official policy for controller v3.5.0 (chart 3.5.0). The
  # hand-written subset was missing ec2:CreateSecurityGroup,
  # ec2:CreateTags and others the controller needs for an NLB.
  policy = file("${path.module}/policies/lbc-iam-policy.json")
}

# ============================================================
# CONTROLLER ROLE
# ============================================================

resource "aws_iam_role" "load_balancer_controller" {
  name = "${local.name}-load-balancer-controller"

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

resource "aws_iam_role_policy_attachment" "load_balancer_controller" {
  role = aws_iam_role.load_balancer_controller.name

  policy_arn = aws_iam_policy.load_balancer_controller.arn
}

# ============================================================
# POD IDENTITY ASSOCIATION
# ============================================================

resource "aws_eks_pod_identity_association" "load_balancer_controller" {
  cluster_name = aws_eks_cluster.main.name

  namespace = "kube-system"

  service_account = "aws-load-balancer-controller"

  role_arn = aws_iam_role.load_balancer_controller.arn

  depends_on = [
    aws_eks_addon.pod_identity,
    aws_iam_role_policy_attachment.load_balancer_controller
  ]
}

# ============================================================
# HELM RELEASE
# ============================================================

resource "helm_release" "aws_load_balancer_controller" {
  name = "aws-load-balancer-controller"

  repository = "https://aws.github.io/eks-charts"

  chart = "aws-load-balancer-controller"

  version = "3.5.0"

  namespace = "kube-system"

  create_namespace = false

  wait = true

  timeout = 600

  values = [
    yamlencode({
      clusterName = aws_eks_cluster.main.name

      region = var.aws_region

      vpcId = aws_vpc.main.id

      replicaCount = 1

      serviceAccount = {
        create = true
        name   = "aws-load-balancer-controller"
      }

      resources = {
        requests = {
          cpu    = "25m"
          memory = "64Mi"
        }

        limits = {
          cpu    = "100m"
          memory = "128Mi"
        }
      }
    })
  ]

  depends_on = [
    aws_eks_pod_identity_association.load_balancer_controller,
    aws_eks_addon.coredns
  ]
}

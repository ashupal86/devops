# ============================================================
# GITHUB OIDC PROVIDER
# ============================================================
#
# Only created when github_repository is set. Leave it empty
# to deploy from your own machine (infra/scripts/deploy.sh).
# ============================================================

locals {
  github_enabled = var.github_repository != ""
}

data "tls_certificate" "github" {
  count = local.github_enabled ? 1 : 0

  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  count = local.github_enabled ? 1 : 0

  url = "https://token.actions.githubusercontent.com"

  client_id_list = [
    "sts.amazonaws.com"
  ]

  thumbprint_list = [
    data.tls_certificate.github[0].certificates[0].sha1_fingerprint
  ]

  tags = local.common_tags
}

# ============================================================
# GITHUB ACTIONS TRUST POLICY
# ============================================================

data "aws_iam_policy_document" "github_assume_role" {
  count = local.github_enabled ? 1 : 0

  statement {
    effect = "Allow"

    actions = [
      "sts:AssumeRoleWithWebIdentity"
    ]

    principals {
      type = "Federated"

      identifiers = [
        aws_iam_openid_connect_provider.github[0].arn
      ]
    }

    condition {
      test = "StringEquals"

      variable = "token.actions.githubusercontent.com:aud"

      values = [
        "sts.amazonaws.com"
      ]
    }

    condition {
      test = "StringLike"

      variable = "token.actions.githubusercontent.com:sub"

      values = [
        "repo:${var.github_repository}:ref:refs/heads/main"
      ]
    }
  }
}

# ============================================================
# GITHUB ACTIONS ROLE
# ============================================================

resource "aws_iam_role" "github_actions" {
  count = local.github_enabled ? 1 : 0

  name = "${local.name}-github-actions"

  assume_role_policy = data.aws_iam_policy_document.github_assume_role[0].json
}

# ============================================================
# ECR PERMISSIONS
# ============================================================

resource "aws_iam_policy" "github_ecr" {
  count = local.github_enabled ? 1 : 0

  name = "${local.name}-github-ecr"

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "ecr:GetAuthorizationToken"
        ]

        Resource = "*"
      },

      {
        Effect = "Allow"

        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:CompleteLayerUpload",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart"
        ]

        Resource = [
          aws_ecr_repository.backend.arn,
          aws_ecr_repository.frontend.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "github_ecr" {
  count = local.github_enabled ? 1 : 0

  role = aws_iam_role.github_actions[0].name

  policy_arn = aws_iam_policy.github_ecr[0].arn
}

# ============================================================
# EKS DESCRIBE PERMISSION
# ============================================================

resource "aws_iam_policy" "github_eks" {
  count = local.github_enabled ? 1 : 0

  name = "${local.name}-github-eks"

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "eks:DescribeCluster"
        ]

        Resource = aws_eks_cluster.main.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "github_eks" {
  count = local.github_enabled ? 1 : 0

  role = aws_iam_role.github_actions[0].name

  policy_arn = aws_iam_policy.github_eks[0].arn
}

# ============================================================
# EKS ACCESS ENTRY
# ============================================================

resource "aws_eks_access_entry" "github_actions" {
  count = local.github_enabled ? 1 : 0

  cluster_name = aws_eks_cluster.main.name

  principal_arn = aws_iam_role.github_actions[0].arn

  type = "STANDARD"
}

resource "aws_eks_access_policy_association" "github_actions" {
  count = local.github_enabled ? 1 : 0

  cluster_name = aws_eks_cluster.main.name

  principal_arn = aws_iam_role.github_actions[0].arn

  policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [
    aws_eks_access_entry.github_actions
  ]
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

provider "kubernetes" {
  host = aws_eks_cluster.main.endpoint

  cluster_ca_certificate = base64decode(
    aws_eks_cluster.main.certificate_authority[0].data
  )

  # A static token expires after 15 minutes, which is shorter
  # than a first apply. exec fetches a fresh one on demand.
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", aws_eks_cluster.main.name, "--region", var.aws_region]
  }
}

provider "helm" {
  kubernetes = {
    host = aws_eks_cluster.main.endpoint

    cluster_ca_certificate = base64decode(
      aws_eks_cluster.main.certificate_authority[0].data
    )

    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", aws_eks_cluster.main.name, "--region", var.aws_region]
    }
  }
}

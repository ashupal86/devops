output "aws_region" {
  description = "AWS region."

  value = var.aws_region
}

output "vpc_id" {
  description = "VPC ID."

  value = aws_vpc.main.id
}

output "eks_cluster_name" {
  description = "EKS cluster name."

  value = aws_eks_cluster.main.name
}

output "eks_cluster_endpoint" {
  description = "EKS Kubernetes API endpoint."

  value = aws_eks_cluster.main.endpoint
}

output "backend_ecr_repository" {
  description = "Backend ECR repository URL."

  value = aws_ecr_repository.backend.repository_url
}

output "frontend_ecr_repository" {
  description = "Frontend ECR repository URL."

  value = aws_ecr_repository.frontend.repository_url
}

output "rds_endpoint" {
  description = "RDS hostname."

  value = aws_db_instance.main.address
}

output "rds_port" {
  description = "RDS port."

  value = aws_db_instance.main.port
}

output "rds_database_name" {
  description = "Database name."

  value = var.database_name
}

output "rds_username" {
  description = "Database username."

  value = var.database_username
}

output "ecr_registry" {
  description = "ECR registry host for docker login."

  value = split("/", aws_ecr_repository.backend.repository_url)[0]
}

output "k8s_namespace" {
  description = "Application namespace."

  value = kubernetes_namespace.app.metadata[0].name
}

output "kubeconfig_command" {
  description = "Command to point kubectl at the cluster."

  value = "aws eks update-kubeconfig --region ${var.aws_region} --name ${aws_eks_cluster.main.name}"
}

output "github_actions_role_arn" {
  description = "GitHub Actions IAM role (empty when github_repository is unset)."

  value = try(aws_iam_role.github_actions[0].arn, "")
}

output "load_balancer_controller_role_arn" {
  description = "AWS Load Balancer Controller IAM role."

  value = aws_iam_role.load_balancer_controller.arn
}

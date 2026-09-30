variable "aws_region" {
  description = "AWS region."
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Project name."
  type        = string
  default     = "social-links"
}

variable "environment" {
  description = "Environment name."
  type        = string
  default     = "prod"
}

# ------------------------------------------------------------
# EKS
# ------------------------------------------------------------

variable "eks_version" {
  description = "EKS Kubernetes version."
  type        = string
  default     = "1.36"
}

variable "node_instance_types" {
  description = "EC2 instance type for EKS worker nodes."
  type        = list(string)
  default     = ["t3.small"]
}

# Two nodes in two AZs so a node failure does not take the app
# down. There is no Cluster Autoscaler, so max_size only caps
# manual scaling; pods scale with the HPA inside these nodes.
# A new account's on-demand vCPU quota (5) fits only 2 x t3.small.
variable "node_min_size" {
  description = "Minimum worker nodes."
  type        = number
  default     = 2
}

variable "node_desired_size" {
  description = "Desired worker nodes."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Maximum worker nodes."
  type        = number
  default     = 2
}

variable "k8s_namespace" {
  description = "Kubernetes namespace for the application."
  type        = string
  default     = "social-links"
}

# ------------------------------------------------------------
# RDS
# ------------------------------------------------------------

variable "database_name" {
  description = "PostgreSQL database name."
  type        = string
  default     = "social_links"
}

variable "database_username" {
  description = "PostgreSQL username."
  type        = string
  default     = "social_links_admin"
}

variable "database_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "database_allocated_storage" {
  description = "RDS storage in GiB."
  type        = number
  default     = 20
}

# ------------------------------------------------------------
# GitHub
# ------------------------------------------------------------

variable "github_repository" {
  description = "GitHub repository in OWNER/REPOSITORY format. Empty skips the GitHub OIDC role."
  type        = string
  default     = ""
}

# ------------------------------------------------------------
# Cost
# ------------------------------------------------------------

variable "budget_limit_usd" {
  description = "Monthly AWS budget in USD for the alert."
  type        = number
  default     = 15
}

variable "budget_alert_email" {
  description = "Email for budget alerts. Empty disables the budget."
  type        = string
  default     = ""
}

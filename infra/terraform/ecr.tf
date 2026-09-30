# ============================================================
# BACKEND REPOSITORY
# ============================================================

resource "aws_ecr_repository" "backend" {
  name = "${local.name}/backend"

  image_tag_mutability = "IMMUTABLE"

  # Test environment: allow `terraform destroy` with images inside.
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

# ============================================================
# FRONTEND REPOSITORY
# ============================================================

resource "aws_ecr_repository" "frontend" {
  name = "${local.name}/frontend"

  image_tag_mutability = "IMMUTABLE"

  # Test environment: allow `terraform destroy` with images inside.
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

# ============================================================
# BACKEND IMAGE LIFECYCLE
# ============================================================

resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1

        description = "Keep the newest 10 images."

        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }

        action = {
          type = "expire"
        }
      }
    ]
  })
}

# ============================================================
# FRONTEND IMAGE LIFECYCLE
# ============================================================

resource "aws_ecr_lifecycle_policy" "frontend" {
  repository = aws_ecr_repository.frontend.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1

        description = "Keep the newest 10 images."

        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }

        action = {
          type = "expire"
        }
      }
    ]
  })
}

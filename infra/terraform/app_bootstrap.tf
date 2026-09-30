# ============================================================
# APPLICATION NAMESPACE
# ============================================================
#
# Terraform owns the namespace so it can place the database
# secret in it. k8s/production.yaml deploys into it.
# ============================================================

resource "kubernetes_namespace" "app" {
  metadata {
    name = var.k8s_namespace
  }

  depends_on = [
    aws_eks_node_group.main
  ]
}

# ============================================================
# BACKEND DATABASE SECRET
# ============================================================
#
# The backend reads DATABASE_URL from this secret, so it
# always points at the RDS instance created in rds.tf with the
# generated password. Nothing sensitive is committed to Git.
#
# The password is URL-encoded because it contains characters
# such as # and ? that would otherwise break the URL.
# ============================================================

resource "kubernetes_secret" "backend_database" {
  metadata {
    name = "backend-database"

    namespace = kubernetes_namespace.app.metadata[0].name
  }

  data = {
    DATABASE_URL = format(
      "postgresql+psycopg://%s:%s@%s:%d/%s?sslmode=require",
      var.database_username,
      urlencode(random_password.database.result),
      aws_db_instance.main.address,
      aws_db_instance.main.port,
      var.database_name
    )
  }

  type = "Opaque"
}

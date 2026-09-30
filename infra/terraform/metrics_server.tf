# ============================================================
# METRICS SERVER
# ============================================================
#
# The HorizontalPodAutoscalers in k8s/production.yaml read pod
# CPU from the metrics API. Without this they never scale.
# ============================================================

resource "helm_release" "metrics_server" {
  name = "metrics-server"

  repository = "https://kubernetes-sigs.github.io/metrics-server/"

  chart = "metrics-server"

  version = "3.14.0"

  namespace = "kube-system"

  wait = true

  timeout = 600

  values = [
    yamlencode({
      resources = {
        requests = {
          cpu    = "25m"
          memory = "64Mi"
        }
      }
    })
  ]

  depends_on = [
    aws_eks_addon.coredns
  ]
}

# ============================================================
# VPC CNI
# ============================================================

resource "aws_eks_addon" "vpc_cni" {
  cluster_name = aws_eks_cluster.main.name

  addon_name = "vpc-cni"

  resolve_conflicts_on_create = "OVERWRITE"

  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [
    aws_eks_node_group.main
  ]
}

# ============================================================
# COREDNS
# ============================================================

resource "aws_eks_addon" "coredns" {
  cluster_name = aws_eks_cluster.main.name

  addon_name = "coredns"

  resolve_conflicts_on_create = "OVERWRITE"

  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [
    aws_eks_node_group.main
  ]
}

# ============================================================
# KUBE-PROXY
# ============================================================

resource "aws_eks_addon" "kube_proxy" {
  cluster_name = aws_eks_cluster.main.name

  addon_name = "kube-proxy"

  resolve_conflicts_on_create = "OVERWRITE"

  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [
    aws_eks_node_group.main
  ]
}

# ============================================================
# POD IDENTITY AGENT
# ============================================================

resource "aws_eks_addon" "pod_identity" {
  cluster_name = aws_eks_cluster.main.name

  addon_name = "eks-pod-identity-agent"

  resolve_conflicts_on_create = "OVERWRITE"

  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [
    aws_eks_node_group.main
  ]
}

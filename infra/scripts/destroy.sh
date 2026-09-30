#!/usr/bin/env bash
# Tear everything down so it stops costing money.
#
# The NLB is created by the AWS Load Balancer Controller, not by
# Terraform, so the frontend Service must be deleted first while
# the controller is still running. Otherwise the NLB and its
# security group are orphaned and block the VPC deletion.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TF="$ROOT/infra/terraform"

if CLUSTER="$(terraform -chdir="$TF" output -raw eks_cluster_name 2>/dev/null)"; then
  REGION="$(terraform -chdir="$TF" output -raw aws_region)"
  NAMESPACE="$(terraform -chdir="$TF" output -raw k8s_namespace)"

  if aws eks update-kubeconfig --region "$REGION" --name "$CLUSTER" >/dev/null 2>&1; then
    echo "==> Deleting app workloads and load balancer"
    kubectl -n "$NAMESPACE" delete -f "$ROOT/k8s/production.yaml" --ignore-not-found --wait=true || true

    # Give the controller time to remove the NLB and its target groups.
    for _ in $(seq 1 36); do
      LEFT="$(aws elbv2 describe-load-balancers --region "$REGION" \
        --query "LoadBalancers[?contains(LoadBalancerName, 'k8s-socialli')].LoadBalancerName" --output text)"
      [ -z "$LEFT" ] && break
      echo "    waiting for load balancer: $LEFT"
      sleep 10
    done
  fi
fi

echo "==> terraform destroy"
terraform -chdir="$TF" destroy -auto-approve

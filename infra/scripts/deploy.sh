#!/usr/bin/env bash
# Build both images, push them to ECR and deploy k8s/production.yaml.
# Run after `terraform apply` in infra/terraform.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TF="$ROOT/infra/terraform"

tf_out() { terraform -chdir="$TF" output -raw "$1"; }

REGION="$(tf_out aws_region)"
CLUSTER="$(tf_out eks_cluster_name)"
REGISTRY="$(tf_out ecr_registry)"
BACKEND_REPO="$(tf_out backend_ecr_repository)"
FRONTEND_REPO="$(tf_out frontend_ecr_repository)"
NAMESPACE="$(tf_out k8s_namespace)"

# Repositories are immutable, so every deploy needs a new tag.
TAG="${IMAGE_TAG:-$(date +%Y%m%d%H%M%S)}"

echo "==> Logging in to ECR ($REGISTRY)"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

echo "==> Building images (tag $TAG)"
docker build --platform linux/amd64 -t "$BACKEND_REPO:$TAG" "$ROOT/backend"
docker build --platform linux/amd64 -t "$FRONTEND_REPO:$TAG" "$ROOT/frontend"

echo "==> Pushing images"
docker push "$BACKEND_REPO:$TAG"
docker push "$FRONTEND_REPO:$TAG"

echo "==> Deploying to $CLUSTER"
aws eks update-kubeconfig --region "$REGION" --name "$CLUSTER" >/dev/null

sed \
  -e "s|BACKEND_IMAGE_PLACEHOLDER|$BACKEND_REPO:$TAG|g" \
  -e "s|FRONTEND_IMAGE_PLACEHOLDER|$FRONTEND_REPO:$TAG|g" \
  "$ROOT/k8s/production.yaml" | kubectl apply -f -

kubectl -n "$NAMESPACE" rollout status deployment/backend --timeout=300s
kubectl -n "$NAMESPACE" rollout status deployment/frontend --timeout=300s

kubectl -n "$NAMESPACE" get pods -o wide

echo "==> Waiting for the load balancer hostname"
for _ in $(seq 1 60); do
  HOST="$(kubectl -n "$NAMESPACE" get svc frontend -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
  [ -n "$HOST" ] && break
  sleep 5
done

echo
echo "App URL: http://${HOST:-<pending>}  (DNS can take 2-3 minutes to resolve)"

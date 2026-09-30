#!/usr/bin/env bash
# Tear everything down so it stops costing money, and leave nothing behind.
#
#   destroy.sh             ask for confirmation, then destroy
#   destroy.sh --yes       no prompt (CI)
#   destroy.sh --dry-run   only print what would be deleted
#
# Phases:
#   1. Kubernetes: stop the Cluster Autoscaler and delete every
#      LoadBalancer Service / Ingress while the AWS Load Balancer
#      Controller is still running, so it removes the NLB, target
#      groups and security groups it created outside Terraform.
#   2. terraform destroy (retried without the Kubernetes/Helm
#      resources if the cluster is already unreachable).
#   3. Sweep: find anything still tagged/named for this stack
#      (leaked NLBs, CNI network interfaces, autoscaled instances,
#      EKS-recreated log groups, a half-deleted VPC from an earlier
#      failed run, ...) and delete it with the AWS CLI.
#   4. Report whatever the tagging API still knows about.
#
# PROJECT / ENVIRONMENT / AWS_REGION default to the Terraform
# outputs or terraform.tfvars, and can be overridden from the env.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TF="$ROOT/infra/terraform"

ASSUME_YES=false
DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=true ;;
    -n|--dry-run) DRY_RUN=true ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

log()  { echo "==> $*"; }
info() { echo "    $*"; }
warn() { echo "    WARN: $*" >&2; }

# Run a mutating command, or just print it in dry-run mode.
# Failures are reported but never abort the teardown.
act() {
  if $DRY_RUN; then
    info "[dry-run] $*"
    return 0
  fi
  local out
  if ! out="$("$@" 2>&1)"; then
    warn "failed: $*"
    [ -n "$out" ] && warn "  ${out//$'\n'/ }"
    return 1
  fi
}

# AWS CLI query that yields whitespace-separated values
# ("None" and errors become empty output).
q() { aws --region "$REGION" --output text "$@" 2>/dev/null | tr '\t' '\n' | grep -v '^None$' | grep -v '^$' || true; }

tfvar() {
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*\"\(.*\)\".*/\1/p" "$TF/terraform.tfvars" 2>/dev/null | head -n1
}
tfdefault() {
  awk -v v="$1" '
    $0 ~ "variable \"" v "\"" { f = 1 }
    f && /default[[:space:]]*=/ { gsub(/.*=[[:space:]]*"|".*/, ""); print; exit }
  ' "$TF/variables.tf" 2>/dev/null
}
setting() { local v; v="$(tfvar "$1")"; [ -n "$v" ] && echo "$v" || tfdefault "$1"; }

# ------------------------------------------------------------
# Preflight
# ------------------------------------------------------------
for bin in aws terraform kubectl jq; do
  command -v "$bin" >/dev/null || { echo "missing required tool: $bin" >&2; exit 1; }
done

REGION="${AWS_REGION:-$(terraform -chdir="$TF" output -raw aws_region 2>/dev/null || setting aws_region)}"
PROJECT="${PROJECT:-$(setting project_name)}"
ENVIRONMENT="${ENVIRONMENT:-$(setting environment)}"
NAME="$PROJECT-$ENVIRONMENT"

if [ -z "$REGION" ] || [ -z "$PROJECT" ] || [ -z "$ENVIRONMENT" ]; then
  echo "could not work out region/project/environment; set AWS_REGION, PROJECT, ENVIRONMENT" >&2
  exit 1
fi

if ! ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text 2>&1)"; then
  echo "AWS credentials are not usable: $ACCOUNT_ID" >&2
  echo "Log in first (e.g. aws sso login / aws login) and re-run." >&2
  exit 1
fi

CLUSTER="$NAME"
NAMESPACE="$(terraform -chdir="$TF" output -raw k8s_namespace 2>/dev/null || setting k8s_namespace)"
NAMESPACE="${NAMESPACE:-social-links}"

# Every VPC for this stack, including ones leaked by earlier runs.
find_vpcs() {
  {
    q ec2 describe-vpcs --filters "Name=tag:Project,Values=$PROJECT" "Name=tag:Environment,Values=$ENVIRONMENT" --query 'Vpcs[].VpcId'
    q ec2 describe-vpcs --filters "Name=tag:Name,Values=$NAME" --query 'Vpcs[].VpcId'
  } | sort -u
}

echo
echo "  Account:     $ACCOUNT_ID"
echo "  Region:      $REGION"
echo "  Stack:       $NAME (Project=$PROJECT, Environment=$ENVIRONMENT)"
echo "  VPCs:        $(find_vpcs | xargs echo)"
echo "  Mode:        $($DRY_RUN && echo dry-run || echo DESTROY)"
echo
if ! $DRY_RUN && ! $ASSUME_YES; then
  if [ ! -t 0 ]; then
    echo "not a terminal; pass --yes to destroy without a prompt" >&2
    exit 1
  fi
  read -r -p "Type '$NAME' to permanently delete everything above: " answer
  [ "$answer" = "$NAME" ] || { echo "aborted"; exit 1; }
fi

START=$SECONDS

# ------------------------------------------------------------
# 1. Kubernetes-created AWS resources
# ------------------------------------------------------------
cluster_status() { q eks describe-cluster --name "$CLUSTER" --query cluster.status; }

if [ "$(cluster_status)" = "ACTIVE" ] && \
   aws eks update-kubeconfig --region "$REGION" --name "$CLUSTER" >/dev/null 2>&1 && \
   kubectl version --request-timeout=15s >/dev/null 2>&1; then

  log "Stopping the Cluster Autoscaler so it cannot add nodes during teardown"
  for d in $(kubectl -n kube-system get deploy -o name 2>/dev/null | grep cluster-autoscaler); do
    act kubectl -n kube-system scale "$d" --replicas=0
  done

  log "Deleting app workloads, LoadBalancer Services and Ingresses"
  act kubectl -n "$NAMESPACE" delete -f "$ROOT/k8s/production.yaml" --ignore-not-found --wait=false
  while read -r ns svc; do
    [ -n "$svc" ] && act kubectl -n "$ns" delete svc "$svc" --wait=false
  done < <(kubectl get svc -A -o json 2>/dev/null \
    | jq -r '.items[] | select(.spec.type == "LoadBalancer") | "\(.metadata.namespace) \(.metadata.name)"')
  act kubectl delete ingress --all -A --wait=false

  if ! $DRY_RUN; then
    info "waiting for the Load Balancer Controller to remove its load balancers"
    for _ in $(seq 1 36); do
      LEFT=""
      for vpc in $(find_vpcs); do
        LEFT+="$(q elbv2 describe-load-balancers --query "LoadBalancers[?VpcId=='$vpc'].LoadBalancerName")"
      done
      [ -z "$LEFT" ] && break
      info "still present: $(echo "$LEFT" | xargs echo)"
      sleep 10
    done
  fi
else
  log "Cluster $CLUSTER is not reachable; skipping the Kubernetes phase (the sweep covers it)"
fi

# ------------------------------------------------------------
# 2. terraform destroy
# ------------------------------------------------------------
tf_state() { terraform -chdir="$TF" state list 2>/dev/null; }

# Kubernetes/Helm resources can only be destroyed through a live
# cluster. Once it is gone, drop them from state: they died with it.
tf_forget_k8s() {
  local r
  for r in $(tf_state | grep -E '^(helm_release|kubernetes_)'); do
    act terraform -chdir="$TF" state rm "$r"
  done
}

tf_destroy() {
  if $DRY_RUN; then
    terraform -chdir="$TF" plan -destroy -input=false -lock=false 2>&1 | tail -n 3
    return 0
  fi
  terraform -chdir="$TF" destroy -auto-approve -input=false
}

if [ ! -d "$TF/.terraform" ]; then
  log "terraform init"
  terraform -chdir="$TF" init -input=false >/dev/null || warn "terraform init failed"
fi

if [ -n "$(tf_state)" ]; then
  log "terraform destroy"
  if ! tf_destroy; then
    warn "terraform destroy failed; retrying without Kubernetes/Helm resources"
    tf_forget_k8s
    tf_destroy || warn "terraform destroy failed again; the sweep will clean up and retry"
  fi
else
  log "Terraform state is empty; going straight to the sweep"
fi

# ------------------------------------------------------------
# 3. Sweep leftovers
# ------------------------------------------------------------
log "Sweeping leftovers for $NAME in $REGION"

# --- EKS (node groups first, then the cluster) ---------------
if [ -n "$(cluster_status)" ]; then
  for ng in $(q eks list-nodegroups --cluster-name "$CLUSTER" --query nodegroups); do
    info "node group $ng"
    act aws eks delete-nodegroup --region "$REGION" --cluster-name "$CLUSTER" --nodegroup-name "$ng"
    $DRY_RUN || aws eks wait nodegroup-deleted --region "$REGION" --cluster-name "$CLUSTER" --nodegroup-name "$ng" 2>/dev/null
  done
  info "EKS cluster $CLUSTER"
  act aws eks delete-cluster --region "$REGION" --name "$CLUSTER"
  $DRY_RUN || aws eks wait cluster-deleted --region "$REGION" --name "$CLUSTER" 2>/dev/null
fi

# --- Auto Scaling groups the node group / autoscaler left ----
for asg in $( {
  q autoscaling describe-auto-scaling-groups --filters "Name=tag:eks:cluster-name,Values=$CLUSTER" --query 'AutoScalingGroups[].AutoScalingGroupName'
  q autoscaling describe-auto-scaling-groups --filters "Name=tag-key,Values=k8s.io/cluster-autoscaler/$CLUSTER" --query 'AutoScalingGroups[].AutoScalingGroupName'
  q autoscaling describe-auto-scaling-groups --filters "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER" --query 'AutoScalingGroups[].AutoScalingGroupName'
} | sort -u ); do
  info "auto scaling group $asg"
  act aws autoscaling delete-auto-scaling-group --region "$REGION" --auto-scaling-group-name "$asg" --force-delete
done

for lt in $(q ec2 describe-launch-templates --filters "Name=tag:eks:cluster-name,Values=$CLUSTER" --query 'LaunchTemplates[].LaunchTemplateId'); do
  info "launch template $lt"
  act aws ec2 delete-launch-template --region "$REGION" --launch-template-id "$lt"
done

# --- RDS ----------------------------------------------------
if [ -n "$(q rds describe-db-instances --db-instance-identifier "$NAME" --query 'DBInstances[].DBInstanceIdentifier')" ]; then
  info "RDS instance $NAME"
  act aws rds modify-db-instance --region "$REGION" --db-instance-identifier "$NAME" --no-deletion-protection --apply-immediately
  act aws rds delete-db-instance --region "$REGION" --db-instance-identifier "$NAME" --skip-final-snapshot --delete-automated-backups
  $DRY_RUN || aws rds wait db-instance-deleted --region "$REGION" --db-instance-identifier "$NAME" 2>/dev/null
fi
for snap in $(q rds describe-db-snapshots --db-instance-identifier "$NAME" --snapshot-type manual --query 'DBSnapshots[].DBSnapshotIdentifier'); do
  info "RDS snapshot $snap"
  act aws rds delete-db-snapshot --region "$REGION" --db-snapshot-identifier "$snap"
done
if [ -n "$(q rds describe-db-subnet-groups --db-subnet-group-name "$NAME-db-subnet-group" --query 'DBSubnetGroups[].DBSubnetGroupName')" ]; then
  info "DB subnet group $NAME-db-subnet-group"
  act aws rds delete-db-subnet-group --region "$REGION" --db-subnet-group-name "$NAME-db-subnet-group"
fi

# --- Everything inside each VPC -------------------------------
sweep_vpc() {
  local vpc="$1" x ids

  info "--- VPC $vpc"

  # Load balancers (NLB from the controller, anything else)
  ids="$(q elbv2 describe-load-balancers --query "LoadBalancers[?VpcId=='$vpc'].LoadBalancerArn")"
  for x in $ids; do
    info "load balancer $x"
    act aws elbv2 delete-load-balancer --region "$REGION" --load-balancer-arn "$x"
  done
  # shellcheck disable=SC2086
  [ -n "$ids" ] && ! $DRY_RUN && aws elbv2 wait load-balancers-deleted --region "$REGION" --load-balancer-arns $ids 2>/dev/null
  for x in $(q elb describe-load-balancers --query "LoadBalancerDescriptions[?VPCId=='$vpc'].LoadBalancerName"); do
    info "classic load balancer $x"
    act aws elb delete-load-balancer --region "$REGION" --load-balancer-name "$x"
  done
  for x in $(q elbv2 describe-target-groups --query "TargetGroups[?VpcId=='$vpc'].TargetGroupArn"); do
    info "target group $x"
    act aws elbv2 delete-target-group --region "$REGION" --target-group-arn "$x"
  done

  # EC2 instances (autoscaled nodes that outlived their ASG)
  ids="$(q ec2 describe-instances --filters "Name=vpc-id,Values=$vpc" \
    "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId')"
  if [ -n "$ids" ]; then
    info "instances $(echo "$ids" | xargs echo)"
    # shellcheck disable=SC2086
    act aws ec2 terminate-instances --region "$REGION" --instance-ids $ids
    # shellcheck disable=SC2086
    $DRY_RUN || aws ec2 wait instance-terminated --region "$REGION" --instance-ids $ids 2>/dev/null
  fi

  # NAT gateways and VPC endpoints (not in the Terraform, but cheap to check)
  ids="$(q ec2 describe-nat-gateways --filter "Name=vpc-id,Values=$vpc" "Name=state,Values=pending,available" --query 'NatGateways[].NatGatewayId')"
  for x in $ids; do
    info "NAT gateway $x"
    act aws ec2 delete-nat-gateway --region "$REGION" --nat-gateway-id "$x"
  done
  # shellcheck disable=SC2086
  [ -n "$ids" ] && ! $DRY_RUN && aws ec2 wait nat-gateway-deleted --region "$REGION" --nat-gateway-ids $ids 2>/dev/null
  ids="$(q ec2 describe-vpc-endpoints --filters "Name=vpc-id,Values=$vpc" --query 'VpcEndpoints[].VpcEndpointId')"
  if [ -n "$ids" ]; then
    info "VPC endpoints $(echo "$ids" | xargs echo)"
    # shellcheck disable=SC2086
    act aws ec2 delete-vpc-endpoints --region "$REGION" --vpc-endpoint-ids $ids
  fi

  # Network interfaces: VPC CNI leaves "available" ENIs behind and
  # ELB/RDS ENIs take a few minutes to go after their owner.
  local tries=30
  $DRY_RUN && tries=1
  for _ in $(seq 1 "$tries"); do
    for x in $(q ec2 describe-network-interfaces --filters "Name=vpc-id,Values=$vpc" "Name=status,Values=available" --query 'NetworkInterfaces[].NetworkInterfaceId'); do
      info "network interface $x"
      act aws ec2 delete-network-interface --region "$REGION" --network-interface-id "$x"
    done
    ids="$(q ec2 describe-network-interfaces --filters "Name=vpc-id,Values=$vpc" --query 'NetworkInterfaces[].NetworkInterfaceId')"
    if [ -z "$ids" ] || $DRY_RUN; then break; fi
    info "waiting for in-use network interfaces: $(echo "$ids" | xargs echo)"
    sleep 10
  done

  # Security groups: drop every rule first so groups that reference
  # each other (cluster SG <-> RDS SG <-> LBC SGs) can be deleted.
  local sgs
  sgs="$(q ec2 describe-security-groups --filters "Name=vpc-id,Values=$vpc" --query "SecurityGroups[?GroupName!='default'].GroupId")"
  for x in $sgs; do
    local rules
    rules="$(q ec2 describe-security-group-rules --filters "Name=group-id,Values=$x" --query 'SecurityGroupRules[?!IsEgress].SecurityGroupRuleId')"
    # shellcheck disable=SC2086
    [ -n "$rules" ] && act aws ec2 revoke-security-group-ingress --region "$REGION" --group-id "$x" --security-group-rule-ids $rules
    rules="$(q ec2 describe-security-group-rules --filters "Name=group-id,Values=$x" --query 'SecurityGroupRules[?IsEgress].SecurityGroupRuleId')"
    # shellcheck disable=SC2086
    [ -n "$rules" ] && act aws ec2 revoke-security-group-egress --region "$REGION" --group-id "$x" --security-group-rule-ids $rules
  done
  for x in $sgs; do
    info "security group $x"
    act aws ec2 delete-security-group --region "$REGION" --group-id "$x"
  done

  # Subnets, route tables, internet gateway, VPC
  for x in $(q ec2 describe-subnets --filters "Name=vpc-id,Values=$vpc" --query 'Subnets[].SubnetId'); do
    info "subnet $x"
    act aws ec2 delete-subnet --region "$REGION" --subnet-id "$x"
  done
  for x in $(q ec2 describe-route-tables --filters "Name=vpc-id,Values=$vpc" \
      --query 'RouteTables[?!(Associations[?Main])].RouteTableId'); do
    for a in $(q ec2 describe-route-tables --route-table-ids "$x" --query 'RouteTables[].Associations[].RouteTableAssociationId'); do
      act aws ec2 disassociate-route-table --region "$REGION" --association-id "$a"
    done
    info "route table $x"
    act aws ec2 delete-route-table --region "$REGION" --route-table-id "$x"
  done
  for x in $(q ec2 describe-internet-gateways --filters "Name=attachment.vpc-id,Values=$vpc" --query 'InternetGateways[].InternetGatewayId'); do
    info "internet gateway $x"
    act aws ec2 detach-internet-gateway --region "$REGION" --internet-gateway-id "$x" --vpc-id "$vpc"
    act aws ec2 delete-internet-gateway --region "$REGION" --internet-gateway-id "$x"
  done
  info "VPC $vpc"
  act aws ec2 delete-vpc --region "$REGION" --vpc-id "$vpc"
}

for vpc in $(find_vpcs); do
  sweep_vpc "$vpc"
done

# --- Regional leftovers outside the VPC -----------------------
for x in $(q ec2 describe-addresses --filters "Name=tag:Project,Values=$PROJECT" "Name=tag:Environment,Values=$ENVIRONMENT" --query 'Addresses[].AllocationId'); do
  info "elastic IP $x"
  act aws ec2 release-address --region "$REGION" --allocation-id "$x"
done

# EBS volumes from PersistentVolumes or orphaned node disks
for x in $( {
  q ec2 describe-volumes --filters "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER" "Name=status,Values=available" --query 'Volumes[].VolumeId'
  q ec2 describe-volumes --filters "Name=tag:eks:cluster-name,Values=$CLUSTER" "Name=status,Values=available" --query 'Volumes[].VolumeId'
} | sort -u ); do
  info "EBS volume $x"
  act aws ec2 delete-volume --region "$REGION" --volume-id "$x"
done

# EKS recreates its control-plane log group while the cluster is
# being deleted, after Terraform has already removed it.
for prefix in "/aws/eks/$CLUSTER/" "/aws/containerinsights/$CLUSTER/" "/$PROJECT/$ENVIRONMENT/"; do
  for x in $(q logs describe-log-groups --log-group-name-prefix "$prefix" --query 'logGroups[].logGroupName'); do
    info "log group $x"
    act aws logs delete-log-group --region "$REGION" --log-group-name "$x"
  done
done

ids="$(q cloudwatch describe-alarms --alarm-name-prefix "$NAME-" --query 'MetricAlarms[].AlarmName')"
if [ -n "$ids" ]; then
  info "alarms $(echo "$ids" | xargs echo)"
  # shellcheck disable=SC2086
  act aws cloudwatch delete-alarms --region "$REGION" --alarm-names $ids
fi

for x in $(q ecr describe-repositories --query "repositories[?starts_with(repositoryName, '$NAME/')].repositoryName"); do
  info "ECR repository $x"
  act aws ecr delete-repository --region "$REGION" --repository-name "$x" --force
done

# --- Global (IAM, budgets) ------------------------------------
for role in $(q iam list-roles --query "Roles[?starts_with(RoleName, '$NAME-')].RoleName"); do
  info "IAM role $role"
  for p in $(q iam list-attached-role-policies --role-name "$role" --query 'AttachedPolicies[].PolicyArn'); do
    act aws iam detach-role-policy --role-name "$role" --policy-arn "$p"
  done
  for p in $(q iam list-role-policies --role-name "$role" --query 'PolicyNames'); do
    act aws iam delete-role-policy --role-name "$role" --policy-name "$p"
  done
  for ip in $(q iam list-instance-profiles-for-role --role-name "$role" --query 'InstanceProfiles[].InstanceProfileName'); do
    act aws iam remove-role-from-instance-profile --instance-profile-name "$ip" --role-name "$role"
    act aws iam delete-instance-profile --instance-profile-name "$ip"
  done
  act aws iam delete-role --role-name "$role"
done

for arn in $(q iam list-policies --scope Local --query "Policies[?starts_with(PolicyName, '$NAME-')].Arn"); do
  info "IAM policy $arn"
  for role in $(q iam list-entities-for-policy --policy-arn "$arn" --query 'PolicyRoles[].RoleName'); do
    act aws iam detach-role-policy --role-name "$role" --policy-arn "$arn"
  done
  for v in $(q iam list-policy-versions --policy-arn "$arn" --query 'Versions[?!IsDefaultVersion].VersionId'); do
    act aws iam delete-policy-version --policy-arn "$arn" --version-id "$v"
  done
  act aws iam delete-policy --policy-arn "$arn"
done

# OIDC providers are account-wide; only delete ones tagged for this stack.
for arn in $(q iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[].Arn'); do
  tags="$(aws iam list-open-id-connect-provider-tags --open-id-connect-provider-arn "$arn" --output json 2>/dev/null \
    | jq -r '.Tags[]? | "\(.Key)=\(.Value)"')"
  if grep -qx "Project=$PROJECT" <<<"$tags" && grep -qx "Environment=$ENVIRONMENT" <<<"$tags"; then
    info "OIDC provider $arn"
    act aws iam delete-open-id-connect-provider --open-id-connect-provider-arn "$arn"
  fi
done

if aws budgets describe-budget --account-id "$ACCOUNT_ID" --budget-name "$NAME-monthly" >/dev/null 2>&1; then
  info "budget $NAME-monthly"
  act aws budgets delete-budget --account-id "$ACCOUNT_ID" --budget-name "$NAME-monthly"
fi

# ------------------------------------------------------------
# Terraform state and local cleanup
# ------------------------------------------------------------
if ! $DRY_RUN && [ -n "$(tf_state | grep -v '^data\.')" ]; then
  log "Reconciling Terraform state with the sweep"
  tf_forget_k8s
  # Everything is gone in AWS now, so a refresh drops the rest.
  terraform -chdir="$TF" destroy -auto-approve -input=false >/dev/null 2>&1 \
    || warn "terraform state still lists: $(tf_state | grep -v '^data\.' | xargs echo)"
fi

if ! $DRY_RUN; then
  CTX="arn:aws:eks:$REGION:$ACCOUNT_ID:cluster/$CLUSTER"
  kubectl config delete-context "$CTX" >/dev/null 2>&1 || true
  kubectl config delete-cluster "$CTX" >/dev/null 2>&1 || true
  kubectl config delete-user "$CTX" >/dev/null 2>&1 || true
  rm -f "$TF/plan.out"
fi

# ------------------------------------------------------------
# 4. Report
# ------------------------------------------------------------
log "Checking for anything still tagged Project=$PROJECT Environment=$ENVIRONMENT"
REMAINING="$(aws resourcegroupstaggingapi get-resources --region "$REGION" \
  --tag-filters "Key=Project,Values=$PROJECT" "Key=Environment,Values=$ENVIRONMENT" \
  --query 'ResourceTagMappingList[].ResourceARN' --output text 2>/dev/null | tr '\t' '\n' | grep -v '^$' || true)"
LEFT_VPCS="$(find_vpcs)"

if [ -z "$REMAINING" ] && [ -z "$LEFT_VPCS" ]; then
  log "Done in $(( (SECONDS - START) / 60 ))m: nothing left for $NAME in $REGION"
else
  [ -n "$LEFT_VPCS" ] && warn "VPC still present: $(echo "$LEFT_VPCS" | xargs echo)"
  if [ -n "$REMAINING" ]; then
    warn "the tagging API still lists these (it can lag a few minutes behind deletes):"
    echo "$REMAINING" | sed 's/^/      /' >&2
  fi
  $DRY_RUN || warn "re-run this script in a few minutes to retry anything that was still in use"
  $DRY_RUN || exit 1
fi

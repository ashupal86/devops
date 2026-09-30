# ============================================================
# EKS APPLICATION LOG GROUP
# ============================================================

resource "aws_cloudwatch_log_group" "application" {
  name = "/social-links/${var.environment}/application"

  # Keep logs for 7 days to control cost.
  retention_in_days = 7

  tags = local.common_tags
}

# ============================================================
# EKS CONTROL PLANE LOG GROUP
# ============================================================
#
# EKS automatically uses /aws/eks/<cluster>/cluster.
# ============================================================

resource "aws_cloudwatch_log_group" "eks" {
  name = "/aws/eks/${local.name}/cluster"

  retention_in_days = 7

  tags = local.common_tags
}

# ============================================================
# RDS CPU ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name = "${local.name}-rds-high-cpu"

  alarm_description = "RDS CPU utilization is above 80%."

  namespace = "AWS/RDS"

  metric_name = "CPUUtilization"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }

  statistic = "Average"

  period = 300

  evaluation_periods = 2

  threshold = 80

  comparison_operator = "GreaterThanThreshold"

  treat_missing_data = "notBreaching"
}

# ============================================================
# RDS STORAGE ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "rds_storage" {
  alarm_name = "${local.name}-rds-low-storage"

  alarm_description = "RDS free storage is below 2 GiB."

  namespace = "AWS/RDS"

  metric_name = "FreeStorageSpace"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }

  statistic = "Average"

  period = 300

  evaluation_periods = 2

  threshold = 2147483648

  comparison_operator = "LessThanThreshold"

  treat_missing_data = "notBreaching"
}

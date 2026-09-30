# ============================================================
# COST GUARDRAIL
# ============================================================
#
# Emails when month-to-date spend passes 50% / 80% / 100% of
# the test budget, or is forecast to exceed it. Set
# budget_alert_email in terraform.tfvars to enable it.
# ============================================================

resource "aws_budgets_budget" "monthly" {
  count = var.budget_alert_email != "" ? 1 : 0

  name = "${local.name}-monthly"

  budget_type = "COST"

  limit_amount = tostring(var.budget_limit_usd)

  limit_unit = "USD"

  time_unit = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 80, 100]

    content {
      comparison_operator = "GREATER_THAN"

      threshold = notification.value

      threshold_type = "PERCENTAGE"

      notification_type = "ACTUAL"

      subscriber_email_addresses = [var.budget_alert_email]
    }
  }

  notification {
    comparison_operator = "GREATER_THAN"

    threshold = 100

    threshold_type = "PERCENTAGE"

    notification_type = "FORECASTED"

    subscriber_email_addresses = [var.budget_alert_email]
  }
}

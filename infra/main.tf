data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name       = "${var.project}-${var.environment}"
  account_id = data.aws_caller_identity.current.account_id
  azs        = slice(data.aws_availability_zones.available.names, 0, 2)

  alarm_email = var.alarm_email != "" ? var.alarm_email : var.notification_email

  use_custom_domain = var.domain_name != "" && var.hosted_zone_id != ""
  site_hostname     = local.use_custom_domain ? var.domain_name : aws_cloudfront_distribution.site.domain_name
  site_url          = "https://${local.site_hostname}"

  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    Course      = "DSO303"
  }
}

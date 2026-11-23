output "site_url" {
  description = "Open this URL to use the platform."
  value       = local.site_url
}

output "api_health_url" {
  value = "${local.site_url}/api/health"
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.site.id
}

output "api_gateway_endpoint" {
  description = "Direct API Gateway URL (requests without the CloudFront origin header are rejected)."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "cognito_hosted_ui" {
  value = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com"
}

output "uploads_bucket" {
  value = aws_s3_bucket.uploads.id
}

output "frontend_bucket" {
  value = aws_s3_bucket.frontend.id
}

output "db_instance_id" {
  value = aws_db_instance.main.identifier
}

output "db_primary_az" {
  description = "AZ of the current primary (the standby runs in the other AZ)."
  value       = aws_db_instance.main.availability_zone
}

output "dashboard_url" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}

output "demo_credentials" {
  description = "Demo users (run: terraform output -json demo_credentials)."
  sensitive   = true
  value       = { for u, _ in local.demo_users : u => random_password.demo[u].result }
}

output "migration_result" {
  value = try(jsondecode(aws_lambda_invocation.migrate.result), aws_lambda_invocation.migrate.result)
}

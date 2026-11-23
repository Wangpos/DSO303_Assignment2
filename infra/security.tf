# Customer-managed KMS key for data at rest (RDS, S3 uploads, Secrets Manager, Backup vault).
resource "aws_kms_key" "main" {
  description             = "${local.name} data-at-rest key"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.main.key_id
}

# ---------- Secrets ----------
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "db" {
  name_prefix             = "${local.name}/db-master-"
  description             = "RDS PostgreSQL credentials read by the Lambda functions"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = var.deletion_protection ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id
  secret_string = jsonencode({
    engine   = "postgres"
    username = aws_db_instance.main.username
    password = random_password.db.result
    host     = aws_db_instance.main.address
    port     = aws_db_instance.main.port
    dbname   = aws_db_instance.main.db_name
  })
}

# Shared secret CloudFront adds to every API request. The API rejects requests
# without it, so nobody can bypass WAF by calling the API Gateway URL directly.
resource "random_password" "origin_verify" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "origin_verify" {
  name_prefix             = "${local.name}/origin-verify-"
  description             = "Header value CloudFront sends to the API origin"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = var.deletion_protection ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "origin_verify" {
  secret_id     = aws_secretsmanager_secret.origin_verify.id
  secret_string = random_password.origin_verify.result
}

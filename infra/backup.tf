# AWS Backup: daily snapshots for 35 days plus monthly snapshots kept 5 years
# (the records-retention requirement), on top of RDS automated backups (point-in-time restore).

resource "aws_backup_vault" "main" {
  name          = "${local.name}-vault"
  kms_key_arn   = aws_kms_key.main.arn
  force_destroy = !var.deletion_protection
}

resource "aws_backup_plan" "main" {
  name = "${local.name}-plan"

  rule {
    rule_name         = "daily-35d"
    target_vault_name = aws_backup_vault.main.name
    schedule          = "cron(0 20 * * ? *)" # 02:00 Bhutan time
    lifecycle {
      delete_after = 35
    }
  }

  rule {
    rule_name         = "monthly-5y"
    target_vault_name = aws_backup_vault.main.name
    schedule          = "cron(0 21 1 * ? *)"
    lifecycle {
      delete_after = 1826
    }
  }
}

resource "aws_iam_role" "backup" {
  name = "${local.name}-backup"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "backup.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "backup" {
  for_each = toset([
    "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup",
    "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForRestores",
  ])
  role       = aws_iam_role.backup.name
  policy_arn = each.value
}

resource "aws_backup_selection" "db" {
  name         = "${local.name}-db"
  plan_id      = aws_backup_plan.main.id
  iam_role_arn = aws_iam_role.backup.arn
  resources    = [aws_db_instance.main.arn]
}

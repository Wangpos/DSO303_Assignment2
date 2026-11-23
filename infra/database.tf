# Amazon RDS for PostgreSQL, Multi-AZ: a primary in one AZ and a synchronous
# standby in the other. Every commit is written to both AZs before it is
# acknowledged (RPO = 0). If the primary's AZ fails, RDS promotes the standby and
# moves the endpoint's DNS name to it automatically (typically 60-120 s).
#
# Production design: Aurora PostgreSQL Serverless v2 (see docs/services.md).
# AWS Free-plan accounts can only create Aurora with "express configuration"
# (single instance, outside the VPC, internet-reachable), so the deployed build
# uses RDS Multi-AZ, which keeps the same private, two-AZ, encrypted design.

resource "aws_db_subnet_group" "main" {
  name       = "${local.name}-db"
  subnet_ids = aws_subnet.data[*].id
  tags       = { Name = "${local.name}-db-subnets" }
}

resource "aws_db_parameter_group" "main" {
  name   = "${local.name}-pg${var.db_engine_version}"
  family = "postgres${var.db_engine_version}"

  # Reject unencrypted client connections (encryption in transit).
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }
}

resource "aws_db_instance" "main" {
  identifier     = "${local.name}-db"
  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  db_name  = "exams"
  username = "examadmin"
  password = random_password.db.result
  port     = 5432

  # Two AZs: primary + synchronous standby.
  multi_az               = var.db_multi_az
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  parameter_group_name   = aws_db_parameter_group.main.name

  # Encryption at rest with the platform's customer-managed KMS key.
  storage_type      = "gp3"
  allocated_storage = var.db_allocated_storage
  storage_encrypted = true
  kms_key_id        = aws_kms_key.main.arn

  # Automated backups + transaction logs every 5 min -> point-in-time restore.
  # (Free-plan accounts allow 1 day; production uses 35. AWS Backup below adds
  # the 5-year monthly snapshots.)
  backup_retention_period      = var.db_backup_retention_days
  backup_window                = "18:00-19:00"         # 00:00-01:00 Bhutan time
  maintenance_window           = "sun:19:30-sun:20:30" # after the backup window
  copy_tags_to_snapshot        = true
  auto_minor_version_upgrade   = true
  allow_major_version_upgrade  = false
  apply_immediately            = true
  performance_insights_enabled = false

  enabled_cloudwatch_logs_exports = ["postgresql"]

  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = !var.deletion_protection
  final_snapshot_identifier = var.deletion_protection ? "${local.name}-db-final" : null
}

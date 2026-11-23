variable "region" {
  description = "Primary AWS region."
  type        = string
  default     = "ap-south-1"
}

variable "project" {
  description = "Short project name used as a prefix for resource names."
  type        = string
  default     = "examhub"
}

variable "environment" {
  description = "Environment name (e.g. lab, prod)."
  type        = string
  default     = "prod"
}

variable "notification_email" {
  description = "Verified SES sender address. In the SES sandbox it is also the only recipient that will receive mail, so demo users are created with this address."
  type        = string
}

variable "alarm_email" {
  description = "Address subscribed to CloudWatch alarm notifications. Defaults to notification_email."
  type        = string
  default     = ""
}

variable "domain_name" {
  description = "Optional custom domain (e.g. exams.example.edu). Leave empty to use the CloudFront default domain."
  type        = string
  default     = ""
}

variable "hosted_zone_id" {
  description = "Route 53 hosted zone ID for domain_name. Required when domain_name is set."
  type        = string
  default     = ""
}

variable "high_availability_nat" {
  description = "One NAT gateway per AZ (true, production) or a single shared NAT gateway (false, cheaper lab setting)."
  type        = bool
  default     = false
}

variable "db_engine_version" {
  description = "RDS PostgreSQL major version (also selects the parameter group family)."
  type        = string
  default     = "17"
}

variable "db_instance_class" {
  description = "RDS instance class. db.t4g.micro fits the Free plan; use db.r7g.large (or Aurora) for exam week."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "Database storage in GiB (gp3)."
  type        = number
  default     = 20
}

variable "db_multi_az" {
  description = "Run a synchronous standby in the second AZ. Must stay true: it is what survives the loss of one AZ."
  type        = bool
  default     = true
}

variable "db_backup_retention_days" {
  description = "Automated backup / point-in-time-restore window in days. 35 for production; AWS Free-plan accounts only allow 1."
  type        = number
  default     = 1
}

variable "api_provisioned_concurrency" {
  description = "Pre-warmed Lambda environments for the API (set to ~50 for exam week once the account concurrency quota is raised)."
  type        = number
  default     = 0
}

variable "waf_ip_rate_limit" {
  description = "Max requests per 5 minutes from a single non-campus IP before WAF blocks it."
  type        = number
  default     = 2000
}

variable "campus_cidrs" {
  description = "Campus NAT egress CIDRs. Thousands of students can share these IPs, so they are exempt from the per-IP rate limit."
  type        = list(string)
  default     = []
}

variable "deletion_protection" {
  description = "Protect the database, user pool and buckets from deletion. Keep false for the lab so tear-down works."
  type        = bool
  default     = false
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention."
  type        = number
  default     = 90
}

variable "create_demo_users" {
  description = "Create demo student, tutor and admin users and seed a demo exam/assignment."
  type        = bool
  default     = true
}
